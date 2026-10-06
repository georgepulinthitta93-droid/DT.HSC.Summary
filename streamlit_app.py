import streamlit as st
import pandas as pd
import json
import uuid
import time
from google import genai
from google.genai import types

# Set Page Configuration
st.set_page_config(page_title="Dubai Customs Data Segregator", layout="wide")

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

import time

def process_documents(files):
    all_results = []
    
    # Stick strictly to Flash models to maximize free quota limits
    candidate_models = [
        'gemini-3.6-flash',
        'gemini-3.5-flash'
    ]
    
    for uploaded_file in files:
        file_bytes = uploaded_file.read()
        success = False
        last_exception = None
        
        for model_name in candidate_models:
            # Try up to 3 times per model with longer backoff when rate-limited
            for attempt in range(3):
                try:
                    response = client.models.generate_content(
                        model=model_name,
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
                    
                    if response.text:
                        parsed_json = json.loads(response.text)
                        if isinstance(parsed_json, list) and len(parsed_json) > 0:
                            all_results.extend(parsed_json)
                            success = True
                            break
                        elif isinstance(parsed_json, dict) and parsed_json:
                            all_results.append(parsed_json)
                            success = True
                            break
                except Exception as e:
                    last_exception = e
                    err_msg = str(e)
                    # If rate-limited (429) or busy (503), wait 5s then retry
                    if "429" in err_msg or "503" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "UNAVAILABLE" in err_msg:
                        time.sleep(5 * (attempt + 1))
                        continue
                    else:
                        break
            
            if success:
                break
                
        if not success and last_exception:
            st.warning("⚠️ Daily API Free-Tier Quota reached on Google AI Studio. Please wait a few minutes or switch your API key to a Pay-As-You-Go project.")
            raise last_exception
            
    return all_results

import io
import uuid
import pandas as pd
import streamlit as st

# ==========================================
# 4. DATA PROCESSING & CONSOLIDATED RENDERING
# ==========================================
if "extracted_data" in st.session_state and st.session_state["extracted_data"]:
    extracted_data = st.session_state["extracted_data"]
    
    # Pre-build Master Consolidated Table across all invoices for top-level download
    all_shipment_rows = []
    
    for idx, inv in enumerate(extracted_data):
        header = inv.get("header", {})
        line_items = inv.get("line_items", [])
        inv_num = header.get("invoice_number", f"Invoice_{idx+1}")
        
        df_items = pd.DataFrame(line_items)
        if not df_items.empty:
            total_qty = df_items["qty"].sum() if "qty" in df_items else 0
            header_net_w = header.get("total_net_weight_kg", 0.0) or 0.0
            header_gross_w = header.get("total_gross_weight_kg", 0.0) or 0.0
            
            # Proportional weight distribution calculations
            if "item_net_weight_kg" not in df_items.columns or df_items["item_net_weight_kg"].isnull().all():
                df_items["NET WEIGHT/KGS"] = (df_items["qty"] / total_qty * header_net_w).round(3) if total_qty > 0 else 0.0
            else:
                df_items["NET WEIGHT/KGS"] = df_items["item_net_weight_kg"].fillna(0.0)
                
            if "item_gross_weight_kg" not in df_items.columns or df_items["item_gross_weight_kg"].isnull().all():
                df_items["GROSS WEIGHT/KGS"] = (df_items["qty"] / total_qty * header_gross_w).round(3) if total_qty > 0 else 0.0
            else:
                df_items["GROSS WEIGHT/KGS"] = df_items["item_gross_weight_kg"].fillna(0.0)

            # Column renaming for Dubai Trade compatibility
            rename_map = {
                "hs_code": "H. S. CODE",
                "description": "DESCRIPTION",
                "condition": "CONDITION",
                "country_of_origin": "COUNTRY OF ORIGIN",
                "unit": "units",
                "qty": "Qty",
                "value": "VALUE (EXCL. VAT)",
                "vat_amount": "VAT AMOUNT",
                "total_value_incl_vat": "TOTAL VALUE (INCL. VAT)",
                "value": "VALUE"
            }
            df_items = df_items.rename(columns=rename_map)
            
            # Standard Dubai Customs Column Ordering
            cols_order = [
                "H. S. CODE", "DESCRIPTION", "CONDITION", "COUNTRY OF ORIGIN", 
                "units", "Qty", "NET WEIGHT/KGS", "GROSS WEIGHT/KGS", 
                "VALUE (EXCL. VAT)", "VAT AMOUNT", "TOTAL VALUE (INCL. VAT)", "VALUE"
            ]
            cols_to_show = [c for c in cols_order if c in df_items.columns]
            df_items = df_items[cols_to_show]
            
            # Insert Invoice Number as Column 1
            df_items.insert(0, "INVOICE NO.", inv_num)
            all_shipment_rows.append(df_items)

    # ------------------------------------------------------------------
    # TOP CONTROL BAR: MASTER EXCEL DOWNLOAD & SUMMARY METRICS
    # ------------------------------------------------------------------
    if all_shipment_rows:
        master_df = pd.concat(all_shipment_rows, ignore_index=True)
        
        st.markdown("### 📊 Master Shipment Declaration Summary")
        
        # Summary Metrics Row
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("Total Invoices", len(extracted_data))
        m_col2.metric("Total Line Items", len(master_df))
        m_col3.metric("Total Net Weight", f"{master_df['NET WEIGHT/KGS'].sum():,.3f} KG")
        
        val_col = "TOTAL VALUE (INCL. VAT)" if "TOTAL VALUE (INCL. VAT)" in master_df.columns else "VALUE"
        m_col4.metric("Total Declaration Value", f"{master_df[val_col].sum():,.2f}")
        
        # Buffer Excel Generation
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            master_df.to_excel(writer, index=False, sheet_name='Consolidated Customs Data')
        
        # TOP EXCEL DOWNLOAD BUTTON
        st.download_button(
            label="📥 Download Master Excel (All Invoices Combined)",
            data=excel_buffer.getvalue(),
            file_name=f"Dubai_Customs_Master_Declaration_{uuid.uuid4().hex[:6]}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
        st.markdown("---")

    # ------------------------------------------------------------------
    # INDIVIDUAL INVOICE BREAKDOWN TABLES BELOW
    # ------------------------------------------------------------------
    st.markdown("### 📄 Individual Invoice Segregation Grids")
    for idx, inv in enumerate(extracted_data):
        header = inv.get("header", {})
        inv_num = header.get("invoice_number", f"Invoice_{idx+1}")
        
        st.subheader(f"Invoice #{inv_num} ({header.get('invoice_type', 'Invoice')})")
        
        # Individual Invoice Cards
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Seller/Exporter", header.get("seller_exporter_name", "N/A"))
        col1.metric("Incoterms", header.get("incoterms", "N/A"))
        col2.metric("Total Value", f"{header.get('currency', '')} {header.get('total_invoice_value', 0.0):,.2f}")
        col2.metric("Payment Terms", header.get("payment_terms", "N/A"))
        col3.metric("Net Weight", f"{header.get('total_net_weight_kg', 0.0)} KG")
        col3.metric("Gross Weight", f"{header.get('total_gross_weight_kg', 0.0)} KG")
        col4.metric("Total Pages", header.get("total_pages", 1))
        col4.metric("Set Invoices", header.get("total_invoices_in_set", 1))

        # Filter lines for this specific invoice
        inv_df = master_df[master_df["INVOICE NO."] == inv_num].drop(columns=["INVOICE NO."])
        
        st.data_editor(
            inv_df, 
            num_rows="dynamic", 
            key=f"editor_{idx}_{inv_num}_{uuid.uuid4().hex[:6]}",
            use_container_width=True
        )
        st.markdown("---")