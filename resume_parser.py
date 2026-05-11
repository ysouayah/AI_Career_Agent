import pdfplumber
import os

def extract_resume_text(file_path):
    """
    Reads a PDF resume and returns the raw text.
    """
    if not os.path.exists(file_path):
        return "Error: Resume file not found. Please check the file path."
        
    print(f"Reading resume: {file_path}...")
    full_text = ""
    
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # extract_text() pulls the raw string data from the PDF
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
                    
        print("Success! Resume text extracted.")
        return full_text.strip()
        
    except Exception as e:
        return f"Error reading PDF: {e}"

# This block lets you test the parser by running this script directly
if __name__ == "__main__":
    # Put a test resume PDF in the same folder and change this name
    test_file = "YSouayah_MasterResume.pdf" 
    
    extracted_data = extract_resume_text(test_file)
    print("\n--- EXTRACTED TEXT PREVIEW ---")
    # We only print the first 500 characters so it doesn't flood your terminal
    print(extracted_data[:500])
    print("\n------------------------------")