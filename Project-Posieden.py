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
            st.error("Invalid OpenSanctions API key. Please check your key and try again.")
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

def clean_vessel_data(df):
    """
    Performs data cleaning on the input DataFrame for vessel entities.
    """
    if df.empty:
        return pd.DataFrame(columns=['name', 'imo'])
    
    initial_rows = len(df)
    
    if 'imo' in df.columns:
        df = df.rename(columns={'imo': 'imoNumber'})
    
    expected_cols = ['name', 'imoNumber']
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ''

    df = df.dropna(subset=['name', 'imoNumber'])
    
    for col in ['name', 'imoNumber']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().apply(
                lambda x: unicodedata.normalize('NFKD', x).encode('ascii', 'ignore').decode('utf-8')
            )

    df = df[df['imoNumber'].str.isnumeric()]
    df['imoNumber'] = df['imoNumber'].apply(lambda x: x.zfill(7))

    df = df[df['name'] != '']
    df = df[df['imoNumber'] != '']
    df = df.drop_duplicates()
    
    st.info(f"Loaded {initial_rows} rows. {len(df)} valid rows found after cleaning.")
    return df

# --- AI Chat Functions ---
def call_ai_api(api_key, chat_history):
    """
    Calls the Gemini API to generate a chat response.
    """
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"
    headers = {
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [{"parts": [{"text": chat_history}]}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, params={"key": api_key}, timeout=60)
        response.raise_for_status()
        result = response.json()
        if result.get("candidates") and result["candidates"][0].get("content") and result["candidates"][0]["content"].get("parts"):
            text = result["candidates"][0]["content"]["parts"][0]["text"]
            return text
        else:
            return "Sorry, I couldn't generate a response. The API returned an unexpected format."
    except requests.exceptions.HTTPError as e:
        st.error(f"HTTP error occurred: {e}")
        st.error("Please check your OpenAI API key and try again.")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        return None

# --- Streamlit App UI ---
st.set_page_config(
    page_title="OpenSanctions Entity Checker",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("OpenSanctions Entity Checker")
st.markdown("Use this app to check a list of vessels, people, or companies against OpenSanctions data.")
st.markdown("---")

# API Key input in the sidebar
st.sidebar.header("API Keys")
st.sidebar.info("You can get a free OpenSanctions API key from [their website](https://www.opensanctions.org/api/) and a free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).")
os_api_key = st.sidebar.text_input("OpenSanctions API key:", type="password", key="os_api_key")
ai_api_key = st.sidebar.text_input("AI Assistant API key:", type="password", key="ai_api_key")

if not os_api_key:
    st.sidebar.warning("Please enter your OpenSanctions API key to use the checks.")

# --- Tabbed interface for different search types ---
tab1, tab2, tab3 = st.tabs(["Vessel Sanctions Check 🚢", "Person/Company Sanctions Check 👤🏢", "AI Chat Assistant 🤖"])

with tab1:
    st.header("Vessel Sanctions Check")
    st.markdown("Check vessels based on their IMO number.")
    st.markdown("---")

    data_source = st.radio(
        "Select Data Source",
        ["Manage Stored Vessels", "Upload a CSV file", "Paste data manually"],
        key="vessel_data_source"
    )
    
    if data_source == "Manage Stored Vessels":
        st.markdown("Add and manage your vessel list below. The list will be saved between sessions.")
        
        with st.form(key='add_vessel_form', clear_on_submit=True):
            st.subheader("Add a New Vessel")
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Vessel Name")
            with col2:
                new_imo_number = st.text_input("IMO Number")
            
            add_button = st.form_submit_button("Add Vessel")

            if add_button:
                if new_name and new_imo_number:
                    formatted_imo = str(new_imo_number).strip().zfill(7)
                    if not formatted_imo.isnumeric():
                        st.error("IMO number must be numeric.")
                    else:
                        new_vessel_data = {'name': new_name, 'imoNumber': formatted_imo}
                        new_vessel_df = pd.DataFrame([new_vessel_data])
                        st.session_state.vessels_df = pd.concat([st.session_state.vessels_df, new_vessel_df]).drop_duplicates(subset='imoNumber', keep='last')
                        st.session_state.vessels_df.to_csv("vessels_data.csv", index=False)
                        st.success(f"Added vessel: {new_name} (IMO: {formatted_imo})")
                else:
                    st.error("Please provide both a name and an IMO number.")

        st.subheader("Your Stored Vessel List")
        if not st.session_state.vessels_df.empty:
            edited_df = st.data_editor(st.session_state.vessels_df, use_container_width=True)
            if not st.session_state.vessels_df.equals(edited_df):
                st.session_state.vessels_df = edited_df
                st.session_state.vessels_df.to_csv("vessels_data.csv", index=False)
                st.rerun()

    elif data_source == "Upload a CSV file":
        st.markdown("Upload a CSV file with `name` and `imo` columns.")
        uploaded_file = st.file_uploader("Choose a CSV file", type="csv", key="vessel_uploader")
        
        if uploaded_file:
            uploaded_df = pd.read_csv(uploaded_file, header=0, dtype=str)
            st.session_state.vessels_to_check = clean_vessel_data(uploaded_df)
            st.subheader("Uploaded Vessel Data")
            st.dataframe(st.session_state.vessels_to_check, use_container_width=True)

    elif data_source == "Paste data manually":
        st.markdown("Paste your data below in `name,imo` format.")
        default_data = """name,imo
ARGO MARIS,9041643
FAKHR 1 (SHARK52),9588639
"""
        pasted_data = st.text_area("Vessel Data", default_data, height=400, key="vessel_paster")
        
        if pasted_data:
            df = pd.read_csv(io.StringIO(pasted_data), sep=None, engine='python')
            st.session_state.vessels_to_check = clean_vessel_data(df)
            st.subheader("Pasted Vessel Data")
            st.dataframe(st.session_state.vessels_to_check, use_container_width=True)

    if st.button("Check Vessels", key='check_vessels_button'):
        if os_api_key:
            vessels_to_check_df = pd.DataFrame()
            if data_source == "Manage Stored Vessels":
                vessels_to_check_df = st.session_state.vessels_df
            elif data_source == "Upload a CSV file" and 'vessels_to_check' in st.session_state:
                vessels_to_check_df = st.session_state.vessels_to_check
            elif data_source == "Paste data manually" and 'vessels_to_check' in st.session_state:
                vessels_to_check_df = st.session_state.vessels_to_check
            
            if not vessels_to_check_df.empty:
                st.subheader("Sanctions Check Results")
                
                results_df_data = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                total_entities = len(vessels_to_check_df)
                
                for i, (_, vessel) in enumerate(vessels_to_check_df.iterrows()):
                    status_text.text(f"Checking entity {i+1} of {total_entities}: {vessel['name']} ({vessel['imoNumber']})")
                    
                    api_query = {
                        "schema": "Vessel",
                        "properties": {
                            "imoNumber": [vessel['imoNumber']]
                        }
                    }
                    
                    response_data = check_sanctions_single(os_api_key, api_query)
                    
                    is_sanctioned = False
                    is_detained = False
                    sanction_lists = "None"
                    match_score = "N/A"
                    sanctioned_id = "N/A"
                    
                    if response_data:
                        response_for_entity = response_data["responses"].get("entity_0")
                        if response_for_entity and response_for_entity.get("results"):
                            best_match = response_for_entity["results"][0]
                            match_score = f"{best_match.get('score', 0):.2f}"
                            
                            if best_match.get("match") is True and best_match.get("score", 0) > 0.7:
                                is_sanctioned = True
                                sanctioned_id = best_match.get("id", "N/A")
                                sanction_lists = ", ".join(best_match.get("datasets", ["Unknown"]))
                            
                            elif "topics" in best_match.get('properties', {}) and any('detention' in topic for topic in best_match['properties']['topics']):
                                is_detained = True
                                sanctioned_id = best_match.get("id", "N/A")
                                sanction_lists = "Detention"
                            else:
                                is_sanctioned = False
                                is_detained = False
                                
                    results_df_data.append({
                        "Name": vessel["name"],
                        "IMO Number": vessel["imoNumber"],
                        "Sanctioned": is_sanctioned,
                        "Detention": is_detained,
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
                    elif row["Detention"]:
                        return ['background-color: #ffff00'] * len(row)
                    else:
                        return [''] * len(row)
                
                st.markdown("---")
                st.subheader("Final Consolidated Results")
                st.dataframe(results_df.style.apply(highlight_sanctioned, axis=1), use_container_width=True)
                st.success("Check complete!")
            else:
                st.warning("No vessels to check. Please provide data.")
        else:
            st.error("Please enter a valid OpenSanctions API key.")


with tab2:
    st.header("Person/Company Sanctions Check")
    st.markdown("Search for a single person or company by providing their details.")
    st.markdown("---")
    
    entity_type = st.radio("Select Entity Type", ["Person", "Company"], key="pc_entity_type")
    
    if entity_type == "Person":
        name = st.text_input("Person's Name", key="person_name")
        
        if st.button("Check Person", key="check_person_button"):
            if os_api_key and name:
                with st.spinner("Checking person against sanctions lists..."):
                    person_properties = {"name": [name]}
                    
                    api_query = {
                        "schema": "Person",
                        "properties": person_properties
                    }

                    response_data = check_sanctions_single(os_api_key, api_query)
                    
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
        company_name = st.text_input("Company Name", key="company_name")
        
        if st.button("Check Company", key="check_company_button"):
            if os_api_key and company_name:
                with st.spinner("Checking company against sanctions lists..."):
                    api_query = {
                        "schema": "Company",
                        "properties": {"name": [company_name]}
                    }

                    response_data = check_sanctions_single(os_api_key, api_query)

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

with tab3:
    st.header("AI Chat Assistant")
    st.markdown("Use this assistant to ask questions about sanctions data, the OpenSanctions API, or any general queries.")
    st.markdown("---")

    if not ai_api_key:
        st.warning("Please enter your AI Assistant API key in the sidebar to use the chat.")
    else:
        # Initialize chat history
        if "messages" not in st.session_state:
            st.session_state.messages = []

        # Display chat messages from history on app rerun
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # React to user input
        if prompt := st.chat_input("What would you like to know?"):
            # Display user message in chat message container
            st.chat_message("user").markdown(prompt)
            # Add user message to chat history
            st.session_state.messages.append({"role": "user", "content": prompt})

            # Call the AI API
            with st.chat_message("assistant"):
                message_placeholder = st.empty()
                full_response = ""
                response = call_ai_api(ai_api_key, prompt)
                
                if response:
                    message_placeholder.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                else:
                    message_placeholder.markdown("Sorry, I could not get a response from the AI assistant.")
