from flask import Flask, render_template, request, make_response, redirect, url_for, session, flash
from functools import wraps # Needed if using password protection
import math
import base64
import os
import io
import time # Import time for logging

# Import the necessary libraries for authentication and Google Drive
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from playwright.sync_api import sync_playwright


# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = 'your-very-strong-secret-key-here'  # Change this to a random string
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Google Drive Configuration
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ['https://www.googleapis.com/auth/drive.file']
GDRIVE_FOLDER_ID = 'YOUR_REGULAR_FOLDER_ID_HERE'  # Make sure this is your folder ID

INVOICE_DATA_CACHE = {}

# --- HELPER FUNCTIONS ---
# ... (number_to_words and get_invoice_data functions remain unchanged) ...
def number_to_words(n):
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    def words(num):
        if num < 20: return ones[num]
        elif num < 100: return tens[num // 10] + (" " + ones[num % 10] if num % 10 != 0 else "")
        elif num < 1000: return ones[num // 100] + " Hundred " + (words(num % 100) if num % 100 != 0 else "")
        elif num < 100000: return words(num // 1000) + " Thousand " + (words(num % 1000) if num % 1000 != 0 else "")
        elif num < 10000000: return words(num // 100000) + " Lakh " + (words(num % 100000) if num % 100000 != 0 else "")
        else: return words(num // 10000000) + " Crore " + (words(num % 10000000) if num % 10000000 != 0 else "")
    return words(n).strip()

def get_invoice_data(form):
    data = { "invoice_no": form.get("invoice_no") or "", "invoice_date": form.get("invoice_date") or "", "buyer_order_no": form.get("buyer_order_no") or "", "supply_date": form.get("supply_date") or "", "transporter_name": form.get("transporter_name") or "", "vehicle_no": form.get("vehicle_no"), "gr_no": form.get("gr_no") or "", "company": { "name": "Select Media House", "gstin": "09AFMPG9060R1ZK", "address": "A-6, Sarla Bagh Extension, Dayal Bagh, Agra - 282005 (U.P.)", "phone": "9837346250", "bank_details": "Bank : Canara Bank, MG Road, Agra\nIFSC Code:- CNRB0000192 A/c : 0192201001908" }, "billed_to": { "name": form.get("client_name") or "", "address": form.get("client_address") or "", "state": form.get("client_state") or "", "state_code": form.get("client_state_code") or "", "gstin": form.get("client_gstin") or "" }, "shipped_to": { "name": form.get("ship_name") or "", "address": form.get("ship_address") or "", "state": form.get("ship_state") or "", "state_code": form.get("ship_state_code") or "", "gstin": form.get("ship_gstin") or "" }, "discount": float(form.get("discount", 0)), "subtotal": 0.0, "cgst_rate": float(form.get("cgst_rate", 0)), "sgst_rate": float(form.get("sgst_rate", 0)), "igst_rate": float(form.get("igst_rate", 0)), "cgst_amount": 0.0, "sgst_amount": 0.0, "igst_amount": 0.0, "round_off": 0.0, "grand_total": 0.0, "amount_in_words": "Rupees only", "reference_no": form.get("reference_no") or "N/A", }
    items = []
    desc_list, hsn_list, qty_list, uom_list, rate_list = form.getlist("item_desc[]"), form.getlist("item_hsn[]"), form.getlist("item_qty[]"), form.getlist("item_uom[]"), form.getlist("item_rate[]")
    for i in range(len(desc_list)):
        if desc_list[i].strip() == "": continue
        qty, rate = float(qty_list[i] or 0), float(rate_list[i] or 0)
        items.append({ "description": desc_list[i], "hsn": hsn_list[i], "qty": qty, "uom": uom_list[i], "rate": rate, "amount": qty * rate })
    FIXED_ITEM_ROWS = 8
    items = items[:FIXED_ITEM_ROWS]
    while len(items) < FIXED_ITEM_ROWS: items.append({ "description": "", "hsn": "", "qty": None, "uom": "", "rate": None, "amount": None })
    data["items"] = items
    subtotal = sum(it["amount"] for it in data["items"] if it["amount"] is not None) - data["discount"]
    cgst_amount, sgst_amount, igst_amount = subtotal * data["cgst_rate"] / 100, subtotal * data["sgst_rate"] / 100, subtotal * data["igst_rate"] / 100
    grand_total = subtotal + cgst_amount + sgst_amount + igst_amount
    rounded_total = math.floor(grand_total)
    round_off = rounded_total - grand_total
    data.update({ "subtotal": subtotal, "cgst_amount": cgst_amount, "sgst_amount": sgst_amount, "igst_amount": igst_amount, "grand_total": rounded_total, "total_tax": cgst_amount + sgst_amount + igst_amount, "round_off": round_off, "amount_in_words": f" {number_to_words(int(rounded_total))} Rupees Only" })
    logo_path = os.path.join(app.root_path, 'static', 'img', 'logo.png')
    try:
        with open(logo_path, "rb") as image_file: data["encoded_logo"] = base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        data["encoded_logo"] = None
    return data

# --- APPLICATION ROUTES ---
@app.route("/")
def home():
    # If using password, redirect to password prompt if not logged in
    # if 'logged_in' not in session:
    #     return redirect(url_for('password_prompt'))
    return '<h2>Welcome! Go to <a href="/new-invoice">New Invoice</a></h2>' # Add logout link if needed

@app.route("/new-invoice", methods=["GET", "POST"])
# @login_required # Uncomment if using password
def new_invoice():
    if request.method == "POST":
        invoice_data = get_invoice_data(request.form)
        invoice_no = invoice_data["invoice_no"]
        INVOICE_DATA_CACHE[invoice_no] = invoice_data
        return redirect(url_for('preview_invoice', invoice_no=invoice_no))
    return render_template("new_invoice.html", invoice_data={})

@app.route("/preview/<invoice_no>")
# @login_required # Uncomment if using password
def preview_invoice(invoice_no):
    invoice_data = INVOICE_DATA_CACHE.get(invoice_no)
    if not invoice_data:
        flash("Invoice data expired, please generate again.", "error")
        return redirect(url_for('new_invoice'))
    invoice_html = render_template("invoice_pdf.html", **invoice_data)
    return render_template("preview.html", invoice_no=invoice_no, invoice_html=invoice_html)

@app.route("/generate-pdf/<invoice_no>")
# @login_required # Uncomment if using password
def generate_pdf(invoice_no):
    invoice_data = INVOICE_DATA_CACHE.get(invoice_no)
    if not invoice_data: return "Invoice data not found.", 404

    rendered_html = render_template("invoice_pdf.html", **invoice_data)

    print(f"[{time.time()}] Starting PDF generation for {invoice_no}...")
    pdf_content = None
    try:
        with sync_playwright() as p:
            print(f"[{time.time()}] Playwright sync started. Launching browser...")
            browser = p.chromium.launch()
            print(f"[{time.time()}] Browser launched. Creating new page...")
            page = browser.new_page()
            print(f"[{time.time()}] Page created. Setting content...")
            page.set_content(rendered_html)
            print(f"[{time.time()}] Content set. Generating PDF (timeout=90000ms)...")
            # --- Increased Timeout Here ---
            pdf_content = page.pdf(format='A4', print_background=True, timeout=90000)
            print(f"[{time.time()}] PDF generated successfully.")
            browser.close()
            print(f"[{time.time()}] Browser closed.")
    except Exception as e:
        print(f"[{time.time()}] ERROR during PDF generation: {e}")
        # Optionally, return a user-friendly error page or message
        return f"Error generating PDF: {e}", 500

    if pdf_content is None:
        return "Error: PDF content could not be generated.", 500

    invoice_filename = f"{invoice_data['invoice_no']}_{invoice_data['invoice_date']}.pdf"
    response = make_response(pdf_content)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={invoice_filename}'
    return response

# --- GOOGLE DRIVE FLOW ---
@app.route('/authorize/<invoice_no>')
# @login_required # Uncomment if using password
def authorize(invoice_no):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    session['upload_invoice_no'] = invoice_no
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state,
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token, 'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri, 'client_id': credentials.client_id,
        'client_secret': credentials.client_secret, 'scopes': credentials.scopes
    }
    return redirect(url_for('upload_to_drive', invoice_no=session.get('upload_invoice_no')))

@app.route('/upload-to-drive/<invoice_no>')
# @login_required # Uncomment if using password
def upload_to_drive(invoice_no):
    if 'credentials' not in session:
        return redirect(url_for('authorize', invoice_no=invoice_no))

    credentials = google.oauth2.credentials.Credentials(**session['credentials'])
    invoice_data = INVOICE_DATA_CACHE.get(invoice_no)
    if not invoice_data:
        flash("Invoice data expired. Please generate it again.", "error")
        return redirect(url_for('new_invoice'))

    rendered_html = render_template("invoice_pdf.html", **invoice_data)

    print(f"[{time.time()}] Starting PDF generation for upload: {invoice_no}...")
    pdf_content = None
    try:
        with sync_playwright() as p:
            print(f"[{time.time()}] Playwright sync started (upload). Launching browser...")
            browser = p.chromium.launch()
            print(f"[{time.time()}] Browser launched (upload). Creating new page...")
            page = browser.new_page()
            print(f"[{time.time()}] Page created (upload). Setting content...")
            page.set_content(rendered_html)
            print(f"[{time.time()}] Content set (upload). Generating PDF (timeout=90000ms)...")
            # --- Increased Timeout Here ---
            pdf_content = page.pdf(format='A4', print_background=True, timeout=90000)
            print(f"[{time.time()}] PDF generated successfully (upload).")
            browser.close()
            print(f"[{time.time()}] Browser closed (upload).")
    except Exception as e:
        print(f"[{time.time()}] ERROR during PDF generation for upload: {e}")
        flash(f"Error generating PDF for upload: {e}", "error")
        return redirect(url_for('preview_invoice', invoice_no=invoice_no))

    if pdf_content is None:
        flash("Error: PDF content could not be generated for upload.", "error")
        return redirect(url_for('preview_invoice', invoice_no=invoice_no))

    try:
        print(f"[{time.time()}] Attempting to upload to Google Drive...")
        service = build('drive', 'v3', credentials=credentials)
        invoice_filename = f"{invoice_data['invoice_no']}_{invoice_data['invoice_date']}.pdf"
        file_metadata = {'name': invoice_filename} # Saves to user's root Drive
        media = MediaIoBaseUpload(io.BytesIO(pdf_content), mimetype='application/pdf')
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        file_link = file.get('webViewLink')
        print(f"[{time.time()}] Upload successful. File ID: {file.get('id')}")
        flash(f"✅ Successfully uploaded '{invoice_filename}'! <a href='{file_link}' target='_blank'>Open File</a>", "success")

    except Exception as e:
        print(f"[{time.time()}] ERROR during Google Drive upload: {e}")
        flash(f"An error occurred during upload: {e}", "error")

    # Keep data in cache for preview refresh
    # if invoice_no in INVOICE_DATA_CACHE:
    #     del INVOICE_DATA_CACHE[invoice_no]

    return redirect(url_for('preview_invoice', invoice_no=invoice_no))


if __name__ == "__main__":
    app.run(debug=True, port=5000)