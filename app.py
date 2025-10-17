from flask import Flask, render_template, request, send_file
import math, os, pdfkit

# --- CONFIGURATION ---
PDF_OUTPUT_DIR = 'generated_pdfs'
os.makedirs(PDF_OUTPUT_DIR, exist_ok=True)

# path to wkhtmltopdf (adjust if installed elsewhere)
path_to_wkhtmltopdf = r'C:\\Program Files\\wkhtmltopdf\\bin\\wkhtmltopdf.exe'
config = pdfkit.configuration(wkhtmltopdf=path_to_wkhtmltopdf)

def number_to_words(n):
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
            "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def words(num):
        if num < 20:
            return ones[num]
        elif num < 100:
            return tens[num // 10] + (" " + ones[num % 10] if num % 10 != 0 else "")
        elif num < 1000:
            return ones[num // 100] + " Hundred " + (words(num % 100) if num % 100 != 0 else "")
        elif num < 100000:
            return words(num // 1000) + " Thousand " + (words(num % 1000) if num % 1000 != 0 else "")
        elif num < 10000000:
            return words(num // 100000) + " Lakh " + (words(num % 100000) if num % 100000 != 0 else "")
        else:
            return words(num // 10000000) + " Crore " + (words(num % 10000000) if num % 10000000 != 0 else "")

    return words(n).strip()

app = Flask(__name__)

@app.route("/")
def home():
    return '<h2>Welcome! Go to <a href="/new-invoice">New Invoice</a></h2>'

@app.route("/new-invoice", methods=["GET", "POST"])
def new_invoice():
    if request.method == "POST":
        data = {
            "invoice_no": request.form.get("invoice_no") or "",
            "invoice_date": request.form.get("invoice_date") or "",
            "buyer_order_no": request.form.get("buyer_order_no") or "",
            "supply_date": request.form.get("supply_date") or "",
            "transporter_name": request.form.get("transporter_name") or "",
            "vehicle_no": request.form.get("vehicle_no"),
            "gr_no": request.form.get("gr_no") or "",
            "company": {
                "name": "Select Media House",
                "gstin": "09AFMPG9060R1ZK",
                "address": "A-6, Sarla Bagh Extension, Dayal Bagh, Agra - 282005 (U.P.)",
                "phone": "9837346250",
                "bank_details": "Bank : Canara Bank, MG Road, Agra\nIFSC Code:- CNRB0000192 A/c : 0192201001908"
            },
            "billed_to": {
                "name": request.form.get("client_name") or "",
                "address": request.form.get("client_address") or "",
                "state": request.form.get("client_state") or "",
                "state_code": request.form.get("client_state_code") or "",
                "gstin": request.form.get("client_gstin") or ""
            },
            "shipped_to": {
                "name": request.form.get("ship_name") or "",
                "address": request.form.get("ship_address") or "",
                "state": request.form.get("ship_state") or "",
                "state_code": request.form.get("ship_state_code") or "",
                "gstin": request.form.get("ship_gstin") or ""
            },
            "discount": float(request.form.get("discount", 0)),
            "subtotal": 0.0,
            "cgst_rate": float(request.form.get("cgst_rate", 0)),
            "sgst_rate": float(request.form.get("sgst_rate", 0)),
            "igst_rate": float(request.form.get("igst_rate", 0)),
            "cgst_amount": 0.0,
            "sgst_amount": 0.0,
            "igst_amount": 0.0,
            "round_off": 0.0,
            "grand_total": 0.0,
            "amount_in_words": "Rupees only",
            "reference_no": request.form.get("reference_no") or "N/A",
        }

        items = []
        desc_list = request.form.getlist("item_desc[]")
        hsn_list = request.form.getlist("item_hsn[]")
        qty_list = request.form.getlist("item_qty[]")
        uom_list = request.form.getlist("item_uom[]")
        rate_list = request.form.getlist("item_rate[]")

        for i in range(len(desc_list)):
            if desc_list[i].strip() == "":
                continue
            qty = float(qty_list[i] or 0)
            rate = float(rate_list[i] or 0)
            items.append({
                "description": desc_list[i],
                "hsn": hsn_list[i],
                "qty": qty,
                "uom": uom_list[i],
                "rate": rate,
                "amount": qty * rate
            })

        FIXED_ITEM_ROWS = 8
        items = items[:FIXED_ITEM_ROWS]
        while len(items) < FIXED_ITEM_ROWS:
            items.append({"description": "", "hsn": "", "qty": None, "uom": "", "rate": None, "amount": None})

        data["items"] = items

        subtotal = sum(it["amount"] for it in data["items"] if it["amount"] is not None) - data["discount"]
        cgst_amount = subtotal * data["cgst_rate"] / 100
        sgst_amount = subtotal * data["sgst_rate"] / 100
        igst_amount = subtotal * data["igst_rate"] / 100
        grand_total = subtotal + cgst_amount + sgst_amount + igst_amount
        total_tax = cgst_amount + sgst_amount + igst_amount
        rounded_total = math.floor(grand_total)
        round_off = rounded_total - grand_total

        data.update({
            "subtotal": subtotal,
            "cgst_amount": cgst_amount,
            "sgst_amount": sgst_amount,
            "igst_amount": igst_amount,
            "grand_total": rounded_total,
            "total_tax": total_tax,
            "round_off": round_off,
            "amount_in_words": f" {number_to_words(int(rounded_total))} Rupees Only"
        })

        return render_template("invoice_pdf.html", **data)

    return render_template("new_invoice.html")


@app.route("/download_invoice/<invoice_no>")
def download_invoice(invoice_no):
    # In real case, load invoice data from a cache or database
    # For demo, re-render from template context (minimal example)
    html = render_template("invoice_pdf.html", invoice_no=invoice_no)
    pdf_path = os.path.join(PDF_OUTPUT_DIR, f"Invoice_{invoice_no}.pdf")
    pdfkit.from_string(html, pdf_path, configuration=config)
    return send_file(pdf_path, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True)