import asyncio
import re
from urllib.parse import unquote
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://html.duckduckgo.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
}


async def extract_indiamart_leads(keyword: str, city: str, max_results: int):
    results = []
    seen_urls = set()

    query = (
        f'site:indiamart.com "{keyword}" "{city}"'
        if city
        else f'site:indiamart.com "{keyword}"'
    )

    Actor.log.info(f"Target Query: {query}")
    Actor.log.info(f"Target Lead Count: {max_results}")

    search_url = "https://html.duckduckgo.com/html/"
    form_data = {"q": query, "b": ""}

    async with httpx.AsyncClient(
        headers=HEADERS, timeout=30.0, follow_redirects=True
    ) as client:
        page_num = 1

        while len(results) < max_results:
            try:
                Actor.log.info(f"Fetching page {page_num}...")
                response = await client.post(
                    search_url, data=form_data, headers=HEADERS
                )

                if response.status_code != 200:
                    Actor.log.error(
                        f"Failed to fetch page {page_num}. Status code: {response.status_code}"
                    )
                    break

                soup = BeautifulSoup(response.text, "lxml")
                result_elements = soup.select(".result")

                if not result_elements:
                    Actor.log.info("No more listings found on search engine.")
                    break

                page_new_leads = []

                for item in result_elements:
                    if len(results) >= max_results:
                        break

                    title_elem = item.select_one(".result__title .result__a")
                    snippet_elem = item.select_one(".result__snippet")

                    if not title_elem:
                        continue

                    href = title_elem.get("href", "")
                    actual_url = href
                    if "uddg=" in href:
                        match = re.search(r"uddg=([^&]+)", href)
                        if match:
                            actual_url = unquote(match.group(1))

                    # Deduplication & Domain Check
                    if actual_url in seen_urls or "indiamart.com" not in actual_url:
                        continue
                    seen_urls.add(actual_url)

                    raw_title = title_elem.get_text(strip=True)
                    raw_snippet = (
                        snippet_elem.get_text(strip=True) if snippet_elem else ""
                    )

                    # Clean Company / Product Name
                    clean_name = re.sub(
                        r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE
                    )
                    clean_name = re.sub(
                        r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer)\s+in.*$",
                        "",
                        clean_name,
                        flags=re.IGNORECASE,
                    ).strip()

                    if not clean_name or len(clean_name) < 3:
                        clean_name = raw_title

                    # Extract Contact Number
                    phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet)
                    phone = (
                        phone_match.group(0) if phone_match else "Available on profile"
                    )

                    # Extract Price
                    price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
                    price = price_match.group(0) if price_match else "Price on Inquiry"

                    lead_data = {
                        "company_or_product": clean_name,
                        "phone": phone,
                        "price": price,
                        "city": city if city else "All India",
                        "indiamart_url": actual_url,
                        "details": raw_snippet,
                    }

                    results.append(lead_data)
                    page_new_leads.append(lead_data)

                # Push real-time batch to Apify Dataset
                if page_new_leads:
                    await Actor.push_data(page_new_leads)
                    Actor.log.info(
                        f"Page {page_num}: Added {len(page_new_leads)} leads. (Total Extracted: {len(results)}/{max_results})"
                    )

                # Find Next Page Form
                next_form = soup.select_one(".nav-link form, form.nav-link")
                if not next_form:
                    Actor.log.info("Reached the final page of listings.")
                    break

                next_data = {}
                for input_tag in next_form.select("input[type='hidden']"):
                    name = input_tag.get("name")
                    value = input_tag.get("value", "")
                    if name:
                        next_data[name] = value

                if not next_data:
                    break

                form_data = next_data
                page_num += 1

                # Polite delay to prevent rate limiting
                await asyncio.sleep(1.5)

            except Exception as e:
                Actor.log.error(f"Error during extraction on page {page_num}: {str(e)}")
                break

    return results


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Solar Panels")
        city = actor_input.get("city", "Delhi")
        max_results = int(actor_input.get("max_results", 100))

        Actor.log.info(
            f"Starting scraper for '{keyword}' (City: '{city}', Max: {max_results})..."
        )

        leads = await extract_indiamart_leads(keyword, city, max_results)

        if leads:
            Actor.log.info(
                f"Successfully extracted and saved {len(leads)} leads into Dataset."
            )
        else:
            Actor.log.warning(
                "No leads found. Check keyword query or search parameters."
            )


if __name__ == "__main__":
    asyncio.run(main())
