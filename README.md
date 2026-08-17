# IndiaMART B2B Suppliers & Lead Extractor

Extract high-quality B2B leads, supplier contact numbers, pricing, and product details directly from IndiaMART in real-time.

## Features

- **Asynchronous & Fast:** Fetches leads rapidly without browser overhead.
- **Lead Contact Details:** Extracts company names, phone numbers, prices, and direct URLs.
- **Location Targeted:** Filter suppliers by specific Indian cities (e.g., Delhi, Mumbai, Ahmedabad, Indore).
- **Multiple Export Formats:** Download data seamlessly in CSV, Excel, JSON, or connect via API.

---

## How to Use

1. **Keyword:** Enter the product or service you want leads for (e.g., Solar Panels, Packaging Boxes, Textiles).
2. **City (Optional):** Enter the target city (e.g., Delhi, Pune, Jaipur). Leave blank for pan-India search.
3. **Max Results:** Choose how many leads you want to extract.
4. Click **Start** to run the actor.

---

## Output Data Structure

The actor outputs clean structured records into the default Apify Dataset:

- **company_or_product:** Supplier or Product listing name
- **phone:** Direct contact / inquiry number
- **price:** Price listed on the profile
- **city:** Target location
- **indiamart_url:** Direct URL to the IndiaMART listing
- **details:** Description and specifications snippet

---

## Use Cases

- **B2B Lead Generation & Sales Prospecting**
- **Market Price Intelligence & Research**
- **Supplier & Wholesaler Discovery**
