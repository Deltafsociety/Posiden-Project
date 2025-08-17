import streamlit as st
import pandas as pd
import requests
import io
import os
import logging
import unicodedata
import json
import re

# Set up logging for better error debugging
logging.basicConfig(level=logging.INFO)

# Define the filename for our persistent data store
ENTITIES_FILE = "entities.csv"

# --- Data Persistence Functions ---

def load_entities():
    """
    Loads entity data from a CSV file. If the file doesn't exist,
    it creates an empty DataFrame with the required columns.
    """
    if os.path.exists(ENTITIES_FILE):
        try:
            return pd.read_csv(ENTITIES_FILE, dtype={'imoNumber': str, 'passportNumber': str, 'registrationNumber': str}).set_index('name', drop=False)
        except Exception as e:
            st.error(f"Error loading entity data from {ENTITIES_FILE}: {e}")
            return pd.DataFrame(columns=['name', 'schema', 'imoNumber', 'passportNumber', 'registrationNumber']).set_index('name', drop=False)
    else:
        return pd.DataFrame(columns=['name', 'schema', 'imoNumber', 'passportNumber', 'registrationNumber']).set_index('name', drop=False)

def save_entities(df):
    """
    Saves the entity DataFrame to a CSV file.
    """
    try:
        df.to_csv(ENTITIES_FILE, index=False)
    except Exception as e:
        st.error(f"Error saving entity data to {ENTITIES_FILE}: {e}")

# --- API Interaction Functions ---

def check_sanctions_single(api_key, entity):
    """
    Sends a single entity to the OpenSanctions API for matching.
    """
    url = "https://api.opensanctions.org/match/default"
    headers = {
        "Authorization": f"ApiKey {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Ensure the entity is a dictionary with the expected keys
    if not isinstance(entity, dict):
        logging.error(f"Invalid entity format for single check: {entity}")
        return None

    queries = {
        "entity_0": {
            "schema": entity.get("schema", "Thing"),
            "properties": entity.get("properties", {})
        }
    }

    payload = {"queries": queries}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as err:
        st.error(f"HTTP Error for entity '{entity.get('name', 'N/A')}': {err}")
        if response.status_code == 401:
            st.error("Invalid API key. Please check your OpenSanctions API key and try again.")
        elif response.status_code == 400:
            st.error(
                f"Bad Request for entity '{entity.get('name', 'N/A')}': The API rejected the data. "
                "The payload that was sent is displayed below for debugging."
            )
            with st.expander("Show API Request Payload"):
                st.json(payload)
        return None
    except requests.exceptions.RequestException as err:
        st.error(f"Request Error for entity '{entity.get('name', 'N/A')}': {err}")
        return None

def clean_input_data(df):
    """
    Performs data cleaning on the input DataFrame for various entity types.
    """
    if df.empty:
        return pd.DataFrame(columns=['name', 'schema', 'imoNumber', 'passportNumber', 'registrationNumber'])

    initial_rows = len(df)

    # Check for simple 'name,imo' format
    if 'name' in df.columns and 'imo' in df.columns and 'schema' not in df.columns:
        df = df.rename(columns={'imo': 'imoNumber'})
        df['schema'] = 'Vessel'
    
    # Add missing columns with empty string as default
    expected_cols = ['name', 'schema', 'imoNumber', 'passportNumber', 'registrationNumber']
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ''

    df = df.dropna(subset=['name', 'schema'])

    # Sanitize and strip whitespace from all relevant columns
    for col in ['name', 'imoNumber', 'passportNumber', 'registrationNumber', 'schema']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().apply(
                lambda x: re.sub(r'[^A-Za-z0-9() -./]+', '', unicodedata.normalize('NFKD', x).encode('ascii', 'ignore').decode('utf-8'))
            )

    # Automatically infer schema if not provided (for name,imo format)
    if df['schema'].str.strip().eq('').all() and 'imoNumber' in df.columns and not df['imoNumber'].str.strip().eq('').all():
        df['schema'] = 'Vessel'
    else:
        # Default to Person if schema is not specified
        df['schema'] = df['schema'].replace('', 'Person')

    # Filter and format IMO numbers for 'Vessel' schema
    vessel_df = df[df['schema'].isin(['Vessel'])].copy()
    vessel_df = vessel_df[vessel_df['imoNumber'].str.isnumeric()]
    vessel_df['imoNumber'] = vessel_df['imoNumber'].apply(lambda x: x.zfill(7))

    # Recombine and remove rows where the name or relevant identifier is empty
    other_df = df[~df['schema'].isin(['Vessel'])].copy()
    df = pd.concat([vessel_df, other_df])
    df = df[df['name'] != '']
    df = df.drop_duplicates()

    st.info(f"Loaded {initial_rows} rows. {len(df)} valid rows found after cleaning.")
    return df

# --- Streamlit App UI ---
st.set_page_config(
    page_title="OpenSanctions API Checker",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("POSIDEN PROJECT")
st.markdown("Use this app to check a list of vessels, people, or companies against OpenSanctions data.")
st.markdown("---")

# API Key input in the sidebar
st.sidebar.header("API Key")
st.sidebar.info("You can get a free API key from [OpenSanctions](https://www.opensanctions.org/api/) for non-profit use.")
api_key = st.sidebar.text_input("Enter your API key:", type="password")

if not api_key:
    st.warning("Please enter your API key in the sidebar to proceed.")

# Initialize or load the entity list in session state
if 'entities_df' not in st.session_state:
    st.session_state.entities_df = load_entities()

# --- Tabbed interface for different search types ---
tab1, tab2 = st.tabs(["Bulk Entity Check", "Single Entity Search"])

with tab1:
    st.header("Bulk Entity Check")
    st.markdown("Choose a method to provide your data. For vessels, a `name,imo` CSV will work. For mixed types, use `name,schema,imoNumber,passportNumber,registrationNumber`.")

    data_source = st.radio(
        "Select Data Source",
        ["Manage Stored Entities", "Upload a CSV file", "Paste data manually"]
    )

    if data_source == "Manage Stored Entities":
        st.markdown("Add and manage your entity list below. The list will be saved between sessions.")
        
        # Input form for adding a new entity
        with st.form(key='add_entity_form', clear_on_submit=True):
            st.subheader("Add a New Entity")
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Name")
                new_schema = st.selectbox("Schema", ["Vessel", "Person", "Company"])
            with col2:
                new_imo_number = st.text_input("IMO Number (for Vessels)")
                new_passport_number = st.text_input("Passport Number (for Persons)")
                new_reg_number = st.text_input("Registration Number (for Companies)")
            
            add_button = st.form_submit_button("Add Entity")

            if add_button:
                new_entity_data = {
                    'name': new_name, 
                    'schema': new_schema,
                    'imoNumber': new_imo_number,
                    'passportNumber': new_passport_number,
                    'registrationNumber': new_reg_number,
                }
                
                new_entity_df = pd.DataFrame([new_entity_data])
                new_entity_df = clean_input_data(new_entity_df)

                if new_entity_df.empty:
                    st.error("Please provide valid data.")
                else:
                    if new_entity_df['name'].iloc[0] in st.session_state.entities_df.index:
                        st.warning(f"Entity '{new_name}' already exists.")
                    else:
                        st.session_state.entities_df = pd.concat([st.session_state.entities_df, new_entity_df])
                        save_entities(st.session_state.entities_df)
                        st.success(f"Added entity: {new_name}")

        # Display the current entity list
        st.subheader("Your Stored Entity List")
        if not st.session_state.entities_df.empty:
            entities_display_df = st.session_state.entities_df.copy()
            entities_display_df['Delete'] = [False] * len(entities_display_df)
            
            edited_df = st.data_editor(entities_display_df, use_container_width=True)

            deleted_rows = edited_df[edited_df['Delete'] == True]
            if not deleted_rows.empty:
                for name_to_delete in deleted_rows.index:
                    st.session_state.entities_df = st.session_state.entities_df.drop(name_to_delete)
                    st.success(f"Entity '{name_to_delete}' deleted.")
                save_entities(st.session_state.entities_df)
                st.rerun()
        else:
            st.info("No entities added yet. Use the form above to add your first entity.")

    elif data_source == "Upload a CSV file":
        st.markdown("Upload a CSV file.")
        uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
        
        if uploaded_file:
            # Try to read with a header first, then without if it fails
            try:
                uploaded_df = pd.read_csv(uploaded_file, header=0, dtype=str)
            except pd.errors.ParserError:
                uploaded_file.seek(0)
                uploaded_df = pd.read_csv(uploaded_file, header=None, names=['name', 'imo'], dtype=str)

            if 'imo' in uploaded_df.columns:
                uploaded_df = uploaded_df.rename(columns={'imo': 'imoNumber'})
            
            st.session_state.uploaded_entities = clean_input_data(uploaded_df)
            st.subheader("Uploaded Entity Data")
            st.dataframe(st.session_state.uploaded_entities, use_container_width=True)

    elif data_source == "Paste data manually":
        st.markdown("Paste your data below. For vessels, use `name,imo`. For mixed types, use `name,schema,imoNumber,passportNumber,registrationNumber`.")
        default_data = """name,imo
ARGO MARIS,9041643
FAKHR 1 (SHARK52),9588639
"""
        pasted_data = st.text_area("Entity Data", default_data, height=400)
        
        if pasted_data:
            # Try to read with a header first, then without if it fails
            try:
                df = pd.read_csv(io.StringIO(pasted_data), header=0, dtype=str)
            except pd.errors.ParserError:
                df = pd.read_csv(io.StringIO(pasted_data), header=None, names=['name', 'imo'], dtype=str)
            
            if 'imo' in df.columns:
                df = df.rename(columns={'imo': 'imoNumber'})
            
            st.session_state.pasted_entities = clean_input_data(df)
            st.subheader("Pasted Entity Data")
            st.dataframe(st.session_state.pasted_entities, use_container_width=True)

    # Centralize the "Check Entities" button
    if st.button("Check Entities", key='check_entities_button'):
        if api_key:
            entities_to_check_df = pd.DataFrame()
            if data_source == "Manage Stored Entities":
                entities_to_check_df = st.session_state.entities_df
            elif data_source == "Upload a CSV file" and 'uploaded_entities' in st.session_state:
                entities_to_check_df = st.session_state.uploaded_entities
            elif data_source == "Paste data manually" and 'pasted_entities' in st.session_state:
                entities_to_check_df = st.session_state.pasted_entities
            
            if not entities_to_check_df.empty:
                st.subheader("Sanctions Check Results")
                
                results_df_data = []
                
                progress_bar = st.progress(0)
                status_text = st.empty()

                total_entities = len(entities_to_check_df)
                
                for i, (_, entity) in enumerate(entities_to_check_df.iterrows()):
                    status_text.text(f"Checking entity {i+1} of {total_entities}: {entity['name']}")
                    
                    properties = {'name': [entity['name']]}
                    if entity['schema'] == 'Vessel' and entity['imoNumber']:
                        properties['imoNumber'] = [entity['imoNumber']]
                    elif entity['schema'] == 'Person' and entity['passportNumber']:
                        properties['passportNumber'] = [entity['passportNumber']]
                    elif entity['schema'] == 'Company' and entity['registrationNumber']:
                        properties['registrationNumber'] = [entity['registrationNumber']]

                    api_query = {
                        "schema": entity['schema'],
                        "properties": properties
                    }
                    
                    response_data = check_sanctions_single(api_key, api_query)

                    is_sanctioned = False
                    sanction_lists = "None"
                    match_score = "N/A"
                    sanctioned_id = "N/A"
                    
                    if response_data:
                        response_for_entity = response_data["responses"].get("entity_0")
                        if response_for_entity and response_for_entity.get("results"):
                            best_match = response_for_entity["results"][0]
                            if best_match.get("match") is True and best_match.get("score", 0) > 0.7:
                                is_sanctioned = True
                                sanctioned_id = best_match.get("id", "N/A")
                                sanction_lists = ", ".join(best_match.get("datasets", ["Unknown"]))
                                match_score = f"{best_match.get('score', 0):.2f}"

                    results_df_data.append({
                        "Name": entity["name"],
                        "Type": entity["schema"],
                        "IMO Number": entity["imoNumber"] if entity["schema"] == "Vessel" else "N/A",
                        "Sanctioned": is_sanctioned,
                        "Sanction Lists": sanction_lists,
                        "Match Score": match_score,
                        "OpenSanctions ID": sanctioned_id
                    })
                    
                    progress_bar.progress((i + 1) / total_entities)

                status_text.text("Check complete!")
                progress_bar.empty()
                
                results_df = pd.DataFrame(results_df_data)

                def highlight_sanctioned(row):
                    if row["Sanctioned"]:
                        return ['background-color: #ff0000; color: white'] * len(row)
                    else:
                        return [''] * len(row)
                
                st.markdown("---")
                st.subheader("Final Consolidated Results")
                st.dataframe(results_df.style.apply(highlight_sanctioned, axis=1), use_container_width=True)
                st.success("Check complete!")
            else:
                st.warning("No entities to check. Please provide data.")

with tab2:
    st.header("Single Entity Search")
    st.markdown("Search for a single person or company by providing their details.")
    
    entity_type = st.radio("Select Entity Type", ["Person", "Company"])
    
    if entity_type == "Person":
        name = st.text_input("Person's Name")
        
        if st.button("Check Person"):
            if api_key and name:
                with st.spinner("Checking person against sanctions lists..."):
                    person_properties = {"name": [name]}
                    
                    api_query = {
                        "schema": "Person",
                        "properties": person_properties
                    }

                    response_data = check_sanctions_single(api_key, api_query)
                    
                    if response_data:
                        response_for_person = response_data["responses"].get("entity_0")
                        
                        if response_for_person and response_for_person.get("results"):
                            best_match = response_for_person["results"][0]
                            is_sanctioned = best_match.get("match") is True and best_match.get("score", 0) > 0.7
                            
                            if is_sanctioned:
                                st.subheader("Match Found! 🔴")
                                
                                st.markdown("---")
                                st.markdown(f"**Sanction Lists:** {', '.join(best_match.get('datasets', ['N/A']))}")
                                st.markdown("### All Match Details")

                                properties_dict = best_match.get('properties', {})
                                data_list = []
                                for key, values in properties_dict.items():
                                    data_list.append({
                                        "Property": key,
                                        "Value(s)": ", ".join(values)
                                    })
                                
                                properties_df = pd.DataFrame(data_list)
                                st.dataframe(properties_df, use_container_width=True)
                                
                            else:
                                st.success("No match found on sanctions lists. ✅")
                        else:
                            st.success("No match found on sanctions lists. ✅")
            elif not name:
                st.warning("Please provide a name to search.")

    elif entity_type == "Company":
        company_name = st.text_input("Company Name")
        
        if st.button("Check Company"):
            if api_key and company_name:
                with st.spinner("Checking company against sanctions lists..."):
                    api_query = {
                        "schema": "Company",
                        "properties": {"name": [company_name]}
                    }

                    response_data = check_sanctions_single(api_key, api_query)

                    if response_data:
                        response_for_company = response_data["responses"].get("entity_0")
                        
                        if response_for_company and response_for_company.get("results"):
                            best_match = response_for_company["results"][0]
                            is_sanctioned = best_match.get("match") is True and best_match.get("score", 0) > 0.7

                            if is_sanctioned:
                                st.subheader("Match Found! 🔴")

                                st.markdown("---")
                                st.markdown(f"**Sanction Lists:** {', '.join(best_match.get('datasets', ['N/A']))}")
                                st.markdown("### All Match Details")

                                properties_dict = best_match.get('properties', {})
                                data_list = []
                                for key, values in properties_dict.items():
                                    data_list.append({
                                        "Property": key,
                                        "Value(s)": ", ".join(values)
                                    })
                                
                                properties_df = pd.DataFrame(data_list)
                                st.dataframe(properties_df, use_container_width=True)
                            else:
                                st.success("No match found on sanctions lists. ✅")
                        else:
                            st.success("No match found on sanctions lists. ✅")
            elif not company_name:
                st.warning("Please provide a company name to search.")
