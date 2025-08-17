Posiden Project
Overview

The Posiden Project is a Streamlit web application designed to help users check vessels, persons, or companies against a comprehensive sanctions database using the OpenSanctions API. This tool allows for both individual lookups and bulk checks from CSV files, with a user-friendly interface that clearly highlights sanctioned entities.
Features

Bulk Entity Checking: Upload a CSV file or paste data to screen multiple vessels, persons, and companies simultaneously.
Persistent Storage: Add or remove entities to a locally saved list that persists between sessions.
Single Entity Search: Perform quick, on-the-fly checks for individual entities with detailed results.
Clear Visuals: Sanctioned entities are highlighted in red for immediate identification.
Robust Data Handling: The application includes a resilient data cleaning process to prevent errors from malformed data.

The complete source code for this project is available on GitHub at the following link:
                https://github.com/Deltafsociety/Posiden-Project
Getting Started
Prerequisites

To run this application, you need to have Python installed on your system. You can install the required libraries using pip.

    pip install -r requirements.txt

Downloading the Code

You can download a copy of the project directly from the GitHub repository using the git clone command. This will create a local copy of all the files on your computer.

    git clone https://github.com/Deltafsociety/Posiden-Project.git

If you already have a copy and need to update it with the latest changes from the repository, you can navigate to the project folder and run git pull.

    cd Posiden-Project
    git pull

Running the Application

Open your terminal and navigate to the project directory.

Run the following command:

    streamlit run app.py

The application will automatically open in your web browser.

Usage

Enter your API Key: Get a free OpenSanctions API key from their website and enter it in the sidebar.

Choose a Data Source:

  Manage Stored Entities: Use the built-in form to add entities one by one. This list is saved locally.

  Upload a CSV File: Upload a CSV file for a bulk check.

  For vessels, the file should contain a name and imo column.

  For mixed entity types, the file should contain name, schema, and optional columns like imoNumber, passportNumber, or registrationNumber.

  Paste Data Manually: Paste data directly into the text area.

    Check for Sanctions: Click the "Check Entities" button to perform the bulk check, or the "Check Person" / "Check Company" button for a single search.

    View Results: The results will be displayed in a table, with sanctioned entries highlighted in red. The single search provides a detailed view of all available information for a match.
