import streamlit as st
import pandas as pd
import json
import time
import io
import uuid
from google import genai
from google.genai import types

# Page Configuration
st.set_page_config(page_title="Dubai Customs Data Segregator", layout="wide")

st.title("📦 Dubai Customs Invoice & HS Code Segregator")
st.caption("Upload Commercial Invoices / Packing Lists / Certificates of Origin (PDFs) to automatically extract header metadata and group line items by HS Code & Country of Origin for Dubai Trade entry.")

# Initialize Gemini Client (Uses GEMINI_API_KEY from st.secrets or environment)
client = genai.Client()

# ==========================================
# AI EXTRACTION PROMPT WITH VAT SEPARATION
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
        "value_excl_vat": 0.0,
        "vat_amount": 0.0,
        "total_value_incl_vat": 0.0
      }
    ]
  }
]

CRITICAL RULES FOR WEIGHT & FINANCIAL DISTRIBUTION:
1. If item_net_weight_kg or item_gross_weight_kg are explicitly stated per item, use those exact numbers.
2. If individual weights are missing, set them to null. The application will automatically calculate the proportional weights based on quantities per HS Code/Origin using the total weights provided in the header.
3. If the invoice presents values without VAT and with VAT separately, populate 'value_excl_vat', 'vat_amount', and 'total_value_incl_vat' independently. If no VAT applies, set vat_amount to 0.0 and value_excl_vat equal to total_value_incl_vat.
4. Ensure 'condition' is strictly "NEW" unless explicitly stated as "USED" or "PERSONAL EFFECTS".
"""

# ==========================================
# STABLE MULTI-MODEL FALLBACK ENGINE
# ==========================================
def process_documents(files):
    all_results = []
    
    # Active Gemini endpoints (avoids deprecated model strings)
    candidate_models = [
        'gemini-2.5-flash',
        'gemini-1.5-flash'
    ]
    
    for uploaded_file in files:
        uploaded_file.seek(0)
        file_bytes = uploaded_file.read()
        success = False
        last_exception = None
        
        for model_name in candidate_models:
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
                    # Pause execution on free-tier rate limits (429/503/RESOURCE_EXHAUSTED)
                    if "429" in err_msg or "503" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        time.sleep(5)
                        continue
                    else:
                        break
            if success:
                break
                
        if not success and last_exception:
            st.warning("⚠️ Free-Tier rate limit reached. Please wait 1 minute before retrying or process files in smaller batches.")
            raise last_exception
            
    return all_results

# ==========================================
# FILE UPLOAD & MANUAL PROCESS BUTTON
# ==========================================
uploaded_files = st.file_uploader(
    "Drag & Drop Invoice PDFs here", 
    type=["pdf"], 
    accept_multiple_files=True
)

# Manual action button trigger
if uploaded_files:
    if st.button("🚀 Process & Segregate for Dubai Customs", type="primary"):
        with st.spinner("Extracting invoice metadata and grouping line items for Dubai Trade..."):
            try:
                raw_data = process_documents(uploaded_files)
                st.session_state["extracted_data"] = raw_data
                st.success("Extraction Complete!")
            except Exception as e:
                st.error(f"Error processing documents: {str(e)}")

# ==========================================
# DATA RENDERING & MASTER EXCEL EXPORT
# ==========================================
if "extracted_data" in st.session_state and st.session_state["extracted_data"]:
    extracted_data = st.session_state["extracted_data"]
    all_shipment_rows = []
    
    # Pre-build Master Table across all invoices
    for idx, inv in enumerate(extracted_data):
        header = inv.get("header", {})
        line_items = inv.get("line_items", [])
        inv_num = header.get("invoice_number", f"Invoice_{idx+1}")
        
        df_items = pd.DataFrame(line_items)
        if not df_items.empty:
            total_qty = df_items["qty"].sum() if "qty" in df_items else 0
            header_net_w = header.get("total_net_weight_kg", 0.0) or 0.0
            header_gross_w = header.get("total_gross_weight_kg", 0.0) or 0.0
            
            # Proportional Weight Distribution Calculations
            if "item_net_weight_kg" not in df_items.columns or df_items["item_net_weight_kg"].isnull().all():
                df_items["NET WEIGHT/KGS"] = (df_items["qty"] / total_qty * header_net_w).round(3) if total_qty > 0 else 0.0
            else:
                df_items["NET WEIGHT/KGS"] = df_items["item_net_weight_kg"].fillna(0.0)
                
            if "item_gross_weight_kg" not in df_items.columns or df_items["item_gross_weight_kg"].isnull().all():
                df_items["GROSS WEIGHT/KGS"] = (df_items["qty"] / total_qty * header_gross_w).round(3) if total_qty > 0 else 0.0
            else:
                df_items["GROSS WEIGHT/KGS"] = df_items["item_gross_weight_kg"].fillna(0.0)

            rename_map = {
                "hs_code": "H. S. CODE",
                "description": "DESCRIPTION",
                "condition": "CONDITION",
                "country_of_origin": "COUNTRY OF ORIGIN",
                "unit": "units",
                "qty": "Qty",
                "value_excl_vat": "VALUE (EXCL. VAT)",
                "vat_amount": "VAT AMOUNT",
                "total_value_incl_vat": "TOTAL VALUE (INCL. VAT)"
            }
            df_items = df_items.rename(columns=rename_map)
            
            cols_order = [
                "H. S. CODE", "DESCRIPTION", "CONDITION", "COUNTRY OF ORIGIN", 
                "units", "Qty", "NET WEIGHT/KGS", "GROSS WEIGHT/KGS", 
                "VALUE (EXCL. VAT)", "VAT AMOUNT", "TOTAL VALUE (INCL. VAT)"
            ]
            cols_to_show = [c for c in cols_order if c in df_items.columns]
            df_items = df_items[cols_to_show]
            
            df_items.insert(0, "INVOICE NO.", inv_num)
            all_shipment_rows.append(df_items)

    # Top-Level Master Excel Download & Metrics
    if all_shipment_rows:
        master_df = pd.concat(all_shipment_rows, ignore_index=True)
        
        st.markdown("---")
        st.markdown("### 📊 Master Shipment Declaration Summary")
        
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        m_col1.metric("Total Invoices", len(extracted_data))
        m_col2.metric("Total Line Items", len(master_df))
        m_col3.metric("Total Net Weight", f"{master_df['NET WEIGHT/KGS'].sum():,.3f} KG")
        
        val_col = "TOTAL VALUE (INCL. VAT)" if "TOTAL VALUE (INCL. VAT)" in master_df.columns else "VALUE (EXCL. VAT)"
        m_col4.metric("Total Declaration Value", f"{master_df[val_col].sum():,.2f}" if val_col in master_df.columns else "0.00")
        
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            master_df.to_excel(writer, index=False, sheet_name='Consolidated Customs Data')
        
        st.download_button(
            label="📥 Download Master Excel (All Invoices Combined)",
            data=excel_buffer.getvalue(),
            file_name=f"Dubai_Customs_Master_Declaration_{uuid.uuid4().hex[:6]}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
        st.markdown("---")

    # Individual Invoice Breakdown Grids
    st.markdown("### 📄 Individual Invoice Segregation Grids")
    for idx, inv in enumerate(extracted_data):
        header = inv.get("header", {})
        inv_num = header.get("invoice_number", f"Invoice_{idx+1}")
        
        st.subheader(f"Invoice #{inv_num} ({header.get('invoice_type', 'Invoice')})")
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Seller/Exporter", header.get("seller_exporter_name", "N/A"))
        col1.metric("Incoterms", header.get("incoterms", "N/A"))
        col2.metric("Total Value", f"{header.get('currency', '')} {header.get('total_invoice_value', 0.0):,.2f}")
        col2.metric("Payment Terms", header.get("payment_terms", "N/A"))
        col3.metric("Net Weight", f"{header.get('total_net_weight_kg', 0.0)} KG")
        col3.metric("Gross Weight", f"{header.get('total_gross_weight_kg', 0.0)} KG")
        col4.metric("Total Pages", header.get("total_pages", 1))
        col4.metric("Set Invoices", header.get("total_invoices_in_set", 1))

        if "master_df" in locals():
            inv_df = master_df[master_df["INVOICE NO."] == inv_num].drop(columns=["INVOICE NO."])
            st.data_editor(
                inv_df, 
                num_rows="dynamic", 
                key=f"editor_{idx}_{inv_num}_{uuid.uuid4().hex[:6]}",
                use_container_width=True
            )
        st.markdown("---")