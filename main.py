import asyncio
import re
from urllib.parse import quote_plus, unquote
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def extract_indiamart_leads(keyword: str, city: str, max_results: int):
    results = []

    query = (
        f'site:indiamart.com "{keyword}" "{city}"'
        if city
        else f'site:indiamart.com "{keyword}"'
    )
    encoded_query = quote_plus(query)

    Actor.log.info(f"Searching IndiaMART supplier index for: {query}")

    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30.0, follow_redirects=True
    ) as client:
        try:
            response = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": ""},
                headers=HEADERS,
            )

            if response.status_code != 200:
                Actor.log.error(f"Search request status: {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, "lxml")
            result_elements = soup.select(".result")

            Actor.log.info(f"Found {len(result_elements)} index listings.")

            for item in result_elements:
                if len(results) >= max_results:
                    break

                title_elem = item.select_one(".result__title .result__a")
                snippet_elem = item.select_one(".result__snippet")

                if not title_elem:
                    continue

                raw_title = title_elem.get_text(strip=True)
                raw_snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

                href = title_elem.get("href", "")
                actual_url = href
                if "uddg=" in href:
                    match = re.search(r"uddg=([^&]+)", href)
                    if match:
                        actual_url = unquote(match.group(1))

                # Clean Company / Product Name
                clean_name = re.sub(
                    r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE
                )
                clean_name = re.sub(
                    r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters)\s+in.*$",
                    "",
                    clean_name,
                    flags=re.IGNORECASE,
                ).strip()

                if not clean_name or len(clean_name) < 3:
                    clean_name = raw_title

                # Extract Phone Number
                phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet)
                phone = phone_match.group(0) if phone_match else "Available on profile"

                # Extract Price
                price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
                price = price_match.group(0) if price_match else "Price on Inquiry"

                results.append(
                    {
                        "keyword": keyword,
                        "city": city or "All India",
                        "company_or_product": clean_name,
                        "price": price,
                        "phone": phone,
                        "indiamart_url": actual_url,
                        "details": raw_snippet,
                    }
                )

        except Exception as e:
            Actor.log.error(f"Error extracting leads: {str(e)}")

    return results


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Solar Panels")
        city = actor_input.get("city", "Delhi")
        max_results = int(actor_input.get("max_results", 20))

        Actor.log.info(f"Extracting IndiaMART leads for '{keyword}' in '{city}'...")

        leads = await extract_indiamart_leads(keyword, city, max_results)

        if leads:
            await Actor.push_data(leads)
            Actor.log.info(f"Successfully saved {len(leads)} leads into Dataset.")
        else:
            Actor.log.warning("No leads found. Check query keywords.")


if __name__ == "__main__":
    asyncio.run(main())
