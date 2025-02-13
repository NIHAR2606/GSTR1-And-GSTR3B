import streamlit as st
import fitz  # PyMuPDF
import pdfplumber
import re
import pandas as pd

# Set Streamlit page layout
st.set_page_config(layout="wide")

# Add sidebar for GST type selection
st.sidebar.title("GST Return Type")
gst_type = st.sidebar.radio("Select GST Return Type", ["GSTR-1", "GSTR-3B"])

# GST State Code Mapping
GST_STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}

# GSTR-1 Functions
def extract_details(pdf_path):
    details = {"GSTIN": "", "State": "", "Legal Name": "", "Month": "", "Financial Year": ""}
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                gstin_match = re.search(r'GSTIN\s*[:\-]?\s*(\d{2}[A-Z0-9]{13})', text)
                if gstin_match:
                    details["GSTIN"] = gstin_match.group(1)
                    details["State"] = GST_STATE_CODES.get(details["GSTIN"][:2], "Unknown")
                
                legal_name_match = re.search(r'Legal name of the registered person\s*[:\-]?\s*(.*)', text)
                if legal_name_match:
                    details["Legal Name"] = legal_name_match.group(1).strip()
                
                month_match = re.search(r'Tax period\s*[:\-]?\s*(\w+)', text)
                if month_match:
                    details["Month"] = month_match.group(1).strip()
                
                fy_match = re.search(r'Financial year\s*[:\-]?\s*(\d{4}-\d{2})', text)
                if fy_match:
                    details["Financial Year"] = fy_match.group(1).strip()
                
                break
    return details

def extract_total_liability(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = "\n".join([page.get_text("text") for page in doc])
    
    pattern = r"Total Liability \(Outward supplies other than Reverse charge\)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)"
    match = re.search(pattern, text)
    
    if match:
        return [match.group(1), match.group(2), match.group(3), match.group(4), match.group(5)]
    return ["Not Found", "", "", "", ""]

# GSTR-3B Functions
def clean_numeric_value(value):
    if value is None:
        return 0.0
    
    if isinstance(value, str):
        value = value.replace("E", "").replace("F", "").strip()
    
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return 0.0

def extract_general_details(text):
    def safe_extract(pattern, text):
        match = re.search(pattern, text)
        return match.group(1).strip() if match else None
    
    return {
        "GSTIN": safe_extract(r"GSTIN\s+([A-Z0-9]+)", text),
        "Legal Name": safe_extract(r"Legal name of the registered person\s+(.+)", text),
        "Date": safe_extract(r"Date of ARN\s+([\d/]+)", text),
        "Financial Year": safe_extract(r"Year\s+(\d{4}-\d{2})", text),
        "Period": safe_extract(r"Period\s+([A-Za-z]+)", text),
    }

def extract_table_4(pdf):
    expected_rows = [
        "A. ITC Available (whether in full or part)",
        "(1) Import of goods",
        "(2) Import of services",
        "(3) Inward supplies liable to reverse charge",
        "(4) Inward supplies from ISD",
        "(5) All other ITC",
        "B. ITC Reversed",
        "(1) As per rules 38,42 & 43 of CGST Rules and section 17(5)",
        "(2) Others",
        "C. Net ITC available (A-B)",
        "D. Other Details",
        "(1) ITC reclaimed which was reversed under Table 4(B)(2) in earlier tax period",
        "(2) Ineligible ITC under section 16(4) & ITC restricted due to PoS rules"
    ]
    
    value_map = {}
    table_started = False
    
    for page in pdf.pages:
        text = page.extract_text()
        tables = page.extract_tables()
        
        if "4. Eligible ITC" in text or "Eligible ITC" in text:
            table_started = True
        
        if table_started:
            for table in tables:
                if not table:
                    continue
                
                for row in table:
                    if not row or len(row) < 4:
                        continue
                    
                    row = [str(cell).strip() if cell is not None else '' for cell in row]
                    row_text = row[0]
                    
                    if "Details" in row_text or "Integrated" in row_text:
                        continue
                    
                    values = []
                    for cell in row[1:5]:
                        try:
                            value = clean_numeric_value(cell)
                            values.append(value)
                        except:
                            values.append(0.0)
                    
                    while len(values) < 4:
                        values.append(0.0)
                    
                    for expected_row in expected_rows:
                        if expected_row.lower().replace(" ", "") in row_text.lower().replace(" ", ""):
                            value_map[expected_row] = values
                            break
            
            if "5." in text or "Details of amount paid" in text or "Payment of tax" in text:
                break
    
    data = []
    for row_header in expected_rows:
        if row_header in value_map:
            data.append([row_header] + value_map[row_header])
        else:
            data.append([row_header] + [0.0] * 4)
    
    df = pd.DataFrame(data, columns=["Details", "Integrated Tax", "Central Tax", "State/UT Tax", "Cess"])
    return df

def extract_table_3_1(pdf):
    expected_columns = ["Nature of Supplies", "Total Taxable Value", "Integrated Tax", "Central Tax", "State/UT Tax", "Cess"]
    
    for page in pdf.pages:
        text = page.extract_text()
        if "3.1" in text and "Nature of Supplies" in text:
            table = page.extract_table()
            if table:
                df = pd.DataFrame(table[1:], columns=table[0])
                df = df.iloc[:, :len(expected_columns)]
                df.columns = expected_columns
                
                for col in expected_columns[1:]:
                    df[col] = df[col].apply(clean_numeric_value)
                return df
    
    return pd.DataFrame(columns=expected_columns)

def extract_table_6_1(pdf):
    expected_columns = [
        "Description", 
        "Total Tax Payable", 
        "Tax Paid Through ITC (Integrated)", 
        "Tax Paid Through ITC (Central)", 
        "Tax Paid Through ITC (State/UT)", 
        "Tax Paid Through ITC (Cess)",
        "Tax Paid in Cash", 
        "Interest Paid in Cash", 
        "Late Fee Paid in Cash"
    ]
    
    for page in pdf.pages:
        text = page.extract_text()
        if "Payment of tax" in text:
            table = page.extract_table()
            if table:
                df = pd.DataFrame(table[1:], columns=table[0])
                df = df.iloc[:, :len(expected_columns)]
                df.columns = expected_columns
                
                for col in expected_columns[1:]:
                    df[col] = df[col].apply(clean_numeric_value)
                return df
    
    return pd.DataFrame(columns=expected_columns)

# Main Application Logic
if gst_type == "GSTR-1":
    st.title("📄 GSTR-1 Extraction Tool")
    st.write("Upload GSTR-1 PDFs to extract GST details")
    
    uploaded_files = st.file_uploader("Upload PDFs", type=["pdf"], accept_multiple_files=True)
    
    if uploaded_files:
        data = []
        for uploaded_file in uploaded_files:
            pdf_bytes = uploaded_file.read()
            details = extract_details(uploaded_file)
            total_liability = extract_total_liability(pdf_bytes)
            data.append([uploaded_file.name] + list(details.values()) + total_liability)
        
        columns = ["File Name", "GSTIN", "State", "Legal Name", "Month", "Financial Year", "Taxable Value", "IGST", "CGST", "SGST", "Cess"]
        df = pd.DataFrame(data, columns=columns)
        
        st.write("### Total Liability (Outward supplies other than Reverse charge) ")
        st.dataframe(df)
        
        def multiselect_with_select_all(label, options):
            selected = st.multiselect(label, ["Select All"] + options, default=["Select All"])
            return options if "Select All" in selected else selected
        
        selected_gstin = multiselect_with_select_all("Filter by GSTIN", df["GSTIN"].unique().tolist())
        selected_state = multiselect_with_select_all("Filter by State", df["State"].unique().tolist())
        selected_legal_name = multiselect_with_select_all("Filter by Legal Name", df["Legal Name"].unique().tolist())
        selected_month = multiselect_with_select_all("Filter by Month", df["Month"].unique().tolist())
        selected_year = multiselect_with_select_all("Filter by Financial Year", df["Financial Year"].unique().tolist())
        
        filtered_df = df
        if selected_gstin:
            filtered_df = filtered_df[filtered_df["GSTIN"].isin(selected_gstin)]
        if selected_state:
            filtered_df = filtered_df[filtered_df["State"].isin(selected_state)]
        if selected_legal_name:
            filtered_df = filtered_df[filtered_df["Legal Name"].isin(selected_legal_name)]
        if selected_month:
            filtered_df = filtered_df[filtered_df["Month"].isin(selected_month)]
        if selected_year:
            filtered_df = filtered_df[filtered_df["Financial Year"].isin(selected_year)]
        
        st.write("### Filtered Results")
        st.dataframe(filtered_df)

else:  # GSTR-3B
    st.title("GSTR-3B Extraction Tool")
    st.write("Upload GSTR-3B PDFs to extract GST details")
    
    uploaded_files = st.file_uploader("Upload GSTR-3B PDFs", type="pdf", accept_multiple_files=True)
    
    if uploaded_files:
        all_general_details = []
        all_table_3_1 = []
        all_table_4 = []
        all_table_6_1 = []
        
        for pdf_file in uploaded_files:
            with pdfplumber.open(pdf_file) as pdf:
                full_text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
                
                general_details = extract_general_details(full_text)
                all_general_details.append(general_details)
                
                table_3_1 = extract_table_3_1(pdf)
                table_3_1["File Name"] = pdf_file.name
                all_table_3_1.append(table_3_1)
                
                table_4 = extract_table_4(pdf)
                table_4["File Name"] = pdf_file.name
                all_table_4.append(table_4)
                
                table_6_1 = extract_table_6_1(pdf)
                table_6_1["File Name"] = pdf_file.name
                all_table_6_1.append(table_6_1)
        
        st.subheader("General Details")
        general_df = pd.DataFrame(all_general_details)
        st.dataframe(general_df)
        
        st.subheader("Table 3.1 - Outward and Reverse Charge Supplies")
        final_table_3_1 = pd.concat(all_table_3_1, ignore_index=True)
        st.dataframe(final_table_3_1)
        
        st.subheader("Table 4 - Eligible ITC")
        final_table_4 = pd.concat(all_table_4, ignore_index=True)
        st.dataframe(final_table_4)
        
        st.subheader("Table 6.1 - Payment of Tax")
        final_table_6_1 = pd.concat(all_table_6_1, ignore_index=True)
        st.dataframe(final_table_6_1)
        
        output_excel = "GSTR3B_Extracted.xlsx"
        with pd.ExcelWriter(output_excel) as writer:
            general_df.to_excel(writer, sheet_name="General Details", index=False)
            final_table_3_1.to_excel(writer, sheet_name="Table 3.1", index=False)
            final_table_4.to_excel(writer, sheet_name="Table 4", index=False)
            final_table_6_1.to_excel(writer, sheet_name="Table 6.1", index=False)
        
        with open(output_excel, "rb") as f:
            st.download_button("Download Extracted Data", f, file_name="GSTR3B_Extracted.xlsx")
