import asyncio
import re
from urllib.parse import quote_plus
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


async def scrape_leads(keyword: str, city: str, max_results: int):
    results = []
    query = f"{keyword} {city}".strip() if city else keyword.strip()
    encoded_query = quote_plus(query)
    url = f"https://dir.indiamart.com/search.mp?ss={encoded_query}"

    Actor.log.info(f"Target URL: {url}")

    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30.0, follow_redirects=True
    ) as client:
        try:
            response = await client.get(url)
            Actor.log.info(
                f"Response Status: {response.status_code}, Length: {len(response.text)} characters"
            )

            if response.status_code != 200:
                Actor.log.error(f"Failed to fetch page. Status: {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, "lxml")

            # Broad card selectors for modern IndiaMART layouts
            listings = soup.find_all(
                lambda tag: tag.name in ["div", "section", "li"]
                and tag.get("class")
                and any(
                    re.search(r"(card|listing|item|supplier|result|crd)", cls, re.I)
                    for cls in tag.get("class")
                )
            )

            Actor.log.info(f"Found {len(listings)} matching blocks on page.")

            seen_names = set()

            for card in listings:
                if len(results) >= max_results:
                    break

                # Extract Company/Title
                name_elem = card.find(
                    ["h2", "h3", "h4", "a", "span"],
                    class_=re.compile(r"company|name|title|cnm|supplier", re.I),
                )
                company_name = name_elem.get_text(strip=True) if name_elem else ""

                if (
                    not company_name
                    or len(company_name) < 3
                    or company_name in seen_names
                ):
                    continue

                seen_names.add(company_name)

                # Extract Price / Product Detail
                price_elem = card.find(class_=re.compile(r"price|prc|cost|rate", re.I))
                price = (
                    price_elem.get_text(strip=True)
                    if price_elem
                    else "Contact Supplier"
                )

                # Extract Location / City
                loc_elem = card.find(class_=re.compile(r"city|loc|address|cty", re.I))
                location = (
                    loc_elem.get_text(strip=True) if loc_elem else (city or "India")
                )

                # Extract Phone / Contact
                phone_elem = card.find(
                    class_=re.compile(r"phone|pns|contact|mobile|call", re.I)
                )
                phone = (
                    phone_elem.get_text(strip=True)
                    if phone_elem
                    else "Available on request"
                )

                # Extract Supplier Link
                link_elem = card.find("a", href=True)
                supplier_url = link_elem["href"] if link_elem else "N/A"
                if supplier_url.startswith("/"):
                    supplier_url = f"https://www.indiamart.com{supplier_url}"

                lead_data = {
                    "search_query": query,
                    "company_name": company_name,
                    "price_or_service": price,
                    "location": location,
                    "contact_phone": phone,
                    "supplier_url": supplier_url,
                }

                results.append(lead_data)

        except Exception as e:
            Actor.log.error(f"Error during extraction: {str(e)}")

    return results


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Solar Panels")
        city = actor_input.get("city", "")
        max_results = int(actor_input.get("max_results", 20))

        Actor.log.info(
            f"Extracting leads for query: '{keyword}', City: '{city}' (Limit: {max_results})"
        )

        leads = await scrape_leads(keyword, city, max_results)

        if leads:
            await Actor.push_data(leads)
            Actor.log.info(f"Pushed {len(leads)} leads to Apify dataset.")
        else:
            Actor.log.warning("No leads found. Check selectors or query.")


if __name__ == "__main__":
    asyncio.run(main())
