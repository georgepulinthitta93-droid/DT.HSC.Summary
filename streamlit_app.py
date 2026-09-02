import streamlit as st
import pandas as pd
import json
import uuid
from google import genai
from google.genai import types

# Set Page Configuration
st.set_page_config(page_title="Dubai Customs Data Segregator", layout="wide")
# Hide Streamlit header, toolbar, GitHub icon, and footer
# Hide Streamlit header, toolbar, footer, and bottom "Manage app" bar
hide_st_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    div[data-testid="stToolbar"] {visibility: hidden; height: 0%;}
    div[data-testid="stDecoration"] {visibility: hidden; height: 0%;}
    div[data-testid="stStatusWidget"] {visibility: hidden;}
    #GithubIcon {visibility: hidden;}
    
    /* Hides the bottom-right Streamlit Cloud 'Manage app' button */
    .stAppDeployButton {display: none !important;}
    div[data-testid="stAppViewBlockContainer"] + div {display: none !important;}
    [data-testid="manage-app-button"] {display: none !important;}
    </style>
"""
st.markdown(hide_st_style, unsafe_allow_html=True)
# ==========================================
# 1. USER AUTHENTICATION MODULE
# ==========================================
USER_CREDENTIALS = {
    "admin": "DubaiCustoms2026!",
    "ops_team": "Khansaheb2026"
}

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        st.title("🔒 Dubai Customs Data Portal Login")
        st.caption("Restricted Access - Authorized Personnel Only")
        
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Log In")
            
            if submit:
                if username in USER_CREDENTIALS and USER_CREDENTIALS[username] == password:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    st.rerun()
                else:
                    st.error("Invalid Username or Password")
        return False
    return True

if not check_password():
    st.stop()

# ==========================================
# 2. MAIN APP & SIDEBAR CONFIGURATION
# ==========================================
st.sidebar.title(f"👤 User: {st.session_state.get('username', 'Team')}")
if st.sidebar.button("Logout"):
    st.session_state["authenticated"] = False
    st.rerun()

st.title("📦 Dubai Customs Invoice & HS Code Segregator")
st.write("Upload Commercial Invoices / Packing Lists / Certificates of Origin (PDFs) to automatically extract header metadata and group line items by **HS Code & Country of Origin** for Dubai Trade entry.")

# API Key Handling (Safe Secrets Reading)
secret_key = ""
try:
    if "GEMINI_API_KEY" in st.secrets:
        secret_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    pass

gemini_api_key = st.sidebar.text_input(
    "Google Gemini API Key", 
    value=secret_key,
    type="password", 
    help="Loaded automatically if configured in secrets.toml."
)

if not gemini_api_key:
    st.warning("⚠️ Please enter your Google Gemini API Key in the sidebar to begin processing documents.")
    st.stop()

client = genai.Client(api_key=gemini_api_key)

# File Uploader
uploaded_files = st.file_uploader(
    "Drag & Drop Invoice PDFs here", 
    type=["pdf"], 
    accept_multiple_files=True
)

# ==========================================
# 3. AI EXTRACTION PROMPT & LOGIC
# ==========================================
EXTRACTION_PROMPT = """
You are an expert Dubai Customs Broker and Data Entry Specialist. 
Analyze the uploaded document(s) carefully. 

For EACH distinct commercial invoice found in the uploaded file(s), extract the following data strictly as a JSON array of objects.

JSON Structure Required:
[
  {
    "header": {
      "invoice_number": "String",
      "total_invoices_in_set": 1,
      "seller_exporter_name": "String",
      "incoterms": "String (e.g. FCA, CIF, FOB)",
      "total_pages": 1,
      "invoice_type": "Commercial Invoice / Proforma / Sales Invoice",
      "total_invoice_value": 0.0,
      "currency": "USD/EUR/AED",
      "payment_terms": "String",
      "total_net_weight_kg": 0.0,
      "total_gross_weight_kg": 0.0
    },
    "line_items": [
      {
        "hs_code": "String",
        "description": "String",
        "condition": "NEW",
        "country_of_origin": "String (2-letter ISO code e.g. IT, US, CN, RO)",
        "unit": "EA / PCS / SET",
        "qty": 1.0,
        "item_net_weight_kg": null,
        "item_gross_weight_kg": null,
        "value": 0.0
      }
    ]
  }
]

CRITICAL RULES FOR WEIGHT DISTRIBUTION:
1. If item_net_weight_kg or item_gross_weight_kg are explicitly stated per item, use those exact numbers.
2. If individual weights are missing, set them to null. The application will automatically calculate the proportional weights based on quantities per HS Code/Origin using the total weights provided in the header.
3. Ensure 'condition' is strictly "NEW" unless explicitly stated as "USED" or "PERSONAL EFFECTS".
"""

def process_documents(files):
    all_results = []
    
    for uploaded_file in files:
        file_bytes = uploaded_file.read()
        
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=[
                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type='application/pdf'
                ),
                EXTRACTION_PROMPT
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        data = json.loads(response.text)
        all_results.extend(data)
        
    return all_results

# ==========================================
# 4. DATA PROCESSING & WEIGHT CALCULATIONS
# ==========================================
if uploaded_files and st.button("🚀 Process & Segregate for Dubai Customs"):
    with st.spinner("Extracting invoice metadata and grouping by HS Codes..."):
        try:
            raw_data = process_documents(uploaded_files)
            st.session_state["extracted_data"] = raw_data
            st.success("Extraction Complete!")
        except Exception as e:
            st.error(f"Error processing documents: {str(e)}")

if "extracted_data" in st.session_state:
    extracted_data = st.session_state["extracted_data"]
    
    for idx, inv in enumerate(extracted_data):
        header = inv.get("header", {})
        line_items = inv.get("line_items", [])
        
        inv_num = header.get("invoice_number", f"Invoice_{idx+1}")
        
        st.subheader(f"📄 Invoice #{inv_num} ({header.get('invoice_type', 'Invoice')})")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Seller/Exporter", header.get("seller_exporter_name", "N/A"))
        col1.metric("Incoterms", header.get("incoterms", "N/A"))
        
        col2.metric("Total Invoice Value", f"{header.get('currency', '')} {header.get('total_invoice_value', 0.0):,.2f}")
        col2.metric("Payment Terms", header.get("payment_terms", "N/A"))
        
        col3.metric("Total Net Weight", f"{header.get('total_net_weight_kg', 0.0)} KG")
        col3.metric("Total Gross Weight", f"{header.get('total_gross_weight_kg', 0.0)} KG")
        
        col4.metric("Total Pages", header.get("total_pages", 1))
        col4.metric("Total Invoices in Set", header.get("total_invoices_in_set", 1))
        
        df_items = pd.DataFrame(line_items)
        
        if not df_items.empty:
            total_qty = df_items["qty"].sum() if "qty" in df_items else 0
            header_net_w = header.get("total_net_weight_kg", 0.0) or 0.0
            header_gross_w = header.get("total_gross_weight_kg", 0.0) or 0.0
            
            if "item_net_weight_kg" not in df_items.columns or df_items["item_net_weight_kg"].isnull().all():
                if total_qty > 0:
                    df_items["NET WEIGHT/KGS"] = (df_items["qty"] / total_qty * header_net_w).round(3)
                else:
                    df_items["NET WEIGHT/KGS"] = 0.0
            else:
                df_items["NET WEIGHT/KGS"] = df_items["item_net_weight_kg"].fillna(0.0)
                
            if "item_gross_weight_kg" not in df_items.columns or df_items["item_gross_weight_kg"].isnull().all():
                if total_qty > 0:
                    df_items["GROSS WEIGHT/KGS"] = (df_items["qty"] / total_qty * header_gross_w).round(3)
                else:
                    df_items["GROSS WEIGHT/KGS"] = 0.0
            else:
                df_items["GROSS WEIGHT/KGS"] = df_items["item_gross_weight_kg"].fillna(0.0)

            rename_map = {
                "hs_code": "H. S. CODE",
                "description": "DESCRIPTION",
                "country_of_origin": "COUNTRY OF ORIGIN",
                "unit": "units",
                "qty": "Qty",
                "value": "VALUE",
                "condition": "CONDITION"
            }
            df_items = df_items.rename(columns=rename_map)
            
            cols_order = ["H. S. CODE", "DESCRIPTION", "CONDITION", "COUNTRY OF ORIGIN", "units", "Qty", "NET WEIGHT/KGS", "GROSS WEIGHT/KGS", "VALUE"]
            cols_to_show = [c for c in cols_order if c in df_items.columns]
            df_items = df_items[cols_to_show]

            st.write("#### ✏️ Dubai Customs Declaration Grid (Editable)")
            edited_df = st.data_editor(
                df_items, 
                num_rows="dynamic", 
                key=f"editor_{idx}_{inv_num}_{uuid.uuid4().hex[:6]}",
                use_container_width=True
            )

            t_col1, t_col2, t_col3 = st.columns(3)
            t_col1.write(f"**Total Net Weight:** {edited_df['NET WEIGHT/KGS'].sum():,.3f} KG")
            t_col2.write(f"**Total Gross Weight:** {edited_df['GROSS WEIGHT/KGS'].sum():,.3f} KG")
            t_col3.write(f"**Total Declaration Value:** {header.get('currency', '')} {edited_df['VALUE'].sum():,.2f}")

        st.markdown("---")