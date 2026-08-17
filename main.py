import asyncio
import re
from urllib.parse import quote_plus
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

async def scrape_leads(keyword: str, city: str, max_results: int):
    results = []
    query = f"{keyword} {city}".strip()
    encoded_query = quote_plus(query)
    url = f"https://dir.indiamart.com/search.mp?ss={encoded_query}"

    Actor.log.info(f"Target URL: {url}")

    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                Actor.log.error(f"Failed to fetch page. Status: {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, "lxml")
            listings = soup.select(".cardLinks, .g-card, .listing-card") or soup.find_all("div", class_=re.compile(r"card|listing|item", re.I))

            Actor.log.info(f"Found potential listings: {len(listings)}")

            for card in listings:
                if len(results) >= max_results:
                    break

                # Extract Company Name
                title_elem = card.find(["h2", "h3", "a"], class_=re.compile(r"title|company|name", re.I))
                company_name = title_elem.get_text(strip=True) if title_elem else "N/A"

                if company_name == "N/A" or len(company_name) < 3:
                    continue

                # Extract Price / Product
                price_elem = card.find(class_=re.compile(r"price|prc", re.I))
                price = price_elem.get_text(strip=True) if price_elem else "Contact Supplier"

                # Extract Location / City
                loc_elem = card.find(class_=re.compile(r"city|location|address", re.I))
                location = loc_elem.get_text(strip=True) if loc_elem else city

                # Extract Contact / Phone number
                phone_elem = card.find(class_=re.compile(r"phone|contact|mobile|pns", re.I))
                phone = phone_elem.get_text(strip=True) if phone_elem else "Available on request"

                # Extract Supplier Link
                link_elem = card.find("a", href=True)
                supplier_url = link_elem["href"] if link_elem else "N/A"
                if supplier_url.startswith("/"):
                    supplier_url = f"https://www.indiamart.com{supplier_url}"

                lead_data = {
                    "keyword": keyword,
                    "company_name": company_name,
                    "price_or_service": price,
                    "location": location,
                    "phone": phone,
                    "supplier_url": supplier_url
                }

                results.append(lead_data)

        except Exception as e:
            Actor.log.error(f"Error during extraction: {str(e)}")

    return results

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Solar Panels")
        city = actor_input.get("city", "Delhi")
        max_results = int(actor_input.get("max_results", 50))

        Actor.log.info(f"Starting IndiaMART B2B Extractor for '{keyword}' in '{city}'...")

        leads = await scrape_leads(keyword, city, max_results)

        if leads:
            await Actor.push_data(leads)
            Actor.log.info(f"Successfully scraped and pushed {len(leads)} leads.")
        else:
            Actor.log.warning("No leads found. Check selectors or query.")

if __name__ == "__main__":
    asyncio.run(main())