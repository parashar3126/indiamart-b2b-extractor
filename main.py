import asyncio
import re
from urllib.parse import quote_plus
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
}


async def scrape_indiamart(keyword: str, city: str, max_results: int):
    results = []
    query = f"{keyword} {city}".strip() if city else keyword.strip()
    encoded_query = quote_plus(query)

    url = f"https://m.indiamart.com/isearch.php?s={encoded_query}"
    Actor.log.info(f"Fetching Mobile Endpoint: {url}")

    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30.0, follow_redirects=True
    ) as client:
        try:
            response = await client.get(url)
            Actor.log.info(
                f"HTTP Status: {response.status_code} | Page Length: {len(response.text)} bytes"
            )

            if response.status_code != 200:
                Actor.log.error(f"Failed to fetch page. Status: {response.status_code}")
                return results

            soup = BeautifulSoup(response.text, "lxml")

            cards = soup.select(
                ".prd-card, .card, .g-card, .listing, div[data-click]"
            ) or soup.find_all(
                "div", class_=re.compile(r"card|item|list|prod|box", re.I)
            )
            Actor.log.info(f"Found {len(cards)} raw blocks on page.")

            seen = set()

            for card in cards:
                if len(results) >= max_results:
                    break

                text = card.get_text(separator=" ", strip=True)
                if len(text) < 20:
                    continue

                title_elem = card.find(["h2", "h3", "h4", "a", "strong"])
                title = (
                    title_elem.get_text(strip=True) if title_elem else "Business Lead"
                )

                if title in seen or len(title) < 3:
                    continue
                seen.add(title)

                price_match = re.search(
                    r"(₹\s*[\d,]+(\s*\/\s*\w+)?|Rs\.?\s*[\d,]+)", text
                )
                price = price_match.group(0) if price_match else "Price on Request"

                phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", text)
                phone = phone_match.group(0) if phone_match else "Available on enquiry"

                results.append(
                    {
                        "search_query": query,
                        "company_or_product": title,
                        "price": price,
                        "phone": phone,
                        "location": city or "India",
                        "preview_snippet": text[:180],
                    }
                )

        except Exception as e:
            Actor.log.error(f"Extraction error: {str(e)}")

    return results


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Solar Panels")
        city = actor_input.get("city", "Delhi")
        max_results = int(actor_input.get("max_results", 20))

        Actor.log.info(
            f"Scraping started for: '{keyword}' in '{city}' (Limit: {max_results})"
        )

        leads = await scrape_indiamart(keyword, city, max_results)

        if leads:
            await Actor.push_data(leads)
            Actor.log.info(f"Success! Pushed {len(leads)} leads to Dataset.")
        else:
            Actor.log.warning("No leads extracted. Check log HTTP status.")


if __name__ == "__main__":
    asyncio.run(main())
