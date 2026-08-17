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
    "Referer": "https://lite.duckduckgo.com/",
}


def parse_page_results(soup: BeautifulSoup, keyword: str, city: str, seen_urls: set):
    page_leads = []

    # 1. Parse Standard HTML View
    result_elements = soup.select(".result")
    if result_elements:
        for item in result_elements:
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

            if actual_url in seen_urls or "indiamart.com" not in actual_url:
                continue
            seen_urls.add(actual_url)

            raw_title = title_elem.get_text(strip=True)
            raw_snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

            clean_name = re.sub(
                r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE
            )
            clean_name = re.sub(
                r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer)\s+in.*$",
                "",
                clean_name,
                flags=re.IGNORECASE,
            ).strip()

            phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet)
            phone = phone_match.group(0) if phone_match else "Available on profile"

            price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
            price = price_match.group(0) if price_match else "Price on Inquiry"

            page_leads.append(
                {
                    "company_or_product": clean_name or raw_title,
                    "phone": phone,
                    "price": price,
                    "city": city if city else "All India",
                    "indiamart_url": actual_url,
                    "details": raw_snippet,
                }
            )

    # 2. Parse Lite View
    lite_links = soup.select(".result-link")
    if lite_links:
        for a_tag in lite_links:
            href = a_tag.get("href", "")
            actual_url = href
            if "uddg=" in href:
                match = re.search(r"uddg=([^&]+)", href)
                if match:
                    actual_url = unquote(match.group(1))

            if actual_url in seen_urls or "indiamart.com" not in actual_url:
                continue
            seen_urls.add(actual_url)

            raw_title = a_tag.get_text(strip=True)
            parent_tr = a_tag.find_parent("tr")
            raw_snippet = ""
            if parent_tr:
                next_tr = parent_tr.find_next_sibling("tr")
                if next_tr:
                    snippet_td = next_tr.select_one(".result-snippet")
                    if snippet_td:
                        raw_snippet = snippet_td.get_text(strip=True)

            clean_name = re.sub(
                r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE
            ).strip()
            clean_name = re.sub(
                r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer)\s+in.*$",
                "",
                clean_name,
                flags=re.IGNORECASE,
            ).strip()

            phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet)
            phone = phone_match.group(0) if phone_match else "Available on profile"

            price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
            price = price_match.group(0) if price_match else "Price on Inquiry"

            page_leads.append(
                {
                    "company_or_product": clean_name or raw_title,
                    "phone": phone,
                    "price": price,
                    "city": city if city else "All India",
                    "indiamart_url": actual_url,
                    "details": raw_snippet,
                }
            )

    return page_leads


async def extract_indiamart_leads(
    keyword: str, city: str, max_results: int, proxy_url: str = None
):
    results = []
    seen_urls = set()

    # Broad query without restrictive double quotes
    clean_keyword = keyword.replace('"', "").strip()
    clean_city = city.replace('"', "").strip() if city else ""

    query = (
        f"site:indiamart.com {clean_keyword} {clean_city}".strip()
        if clean_city
        else f"site:indiamart.com {clean_keyword}".strip()
    )

    Actor.log.info(f"Optimized Query: {query}")
    Actor.log.info(f"Target Count: {max_results} leads")

    search_url = "https://lite.duckduckgo.com/lite/"
    form_data = {"q": query, "kl": "in-en"}

    client_kwargs = {
        "headers": HEADERS,
        "timeout": 30.0,
        "follow_redirects": True,
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        page_num = 1

        while len(results) < max_results:
            try:
                Actor.log.info(f"Fetching page {page_num}...")
                response = await client.post(
                    search_url, data=form_data, headers=HEADERS
                )

                if response.status_code != 200 or len(response.text) < 400:
                    Actor.log.warning(
                        f"Response status: {response.status_code}. Retrying with GET fallback..."
                    )
                    response = await client.get(
                        "https://html.duckduckgo.com/html/",
                        params={"q": query},
                        headers=HEADERS,
                    )

                soup = BeautifulSoup(response.text, "lxml")
                page_new_leads = parse_page_results(
                    soup, clean_keyword, clean_city, seen_urls
                )

                if not page_new_leads:
                    Actor.log.info("No more matching leads found.")
                    break

                for lead in page_new_leads:
                    if len(results) >= max_results:
                        break
                    results.append(lead)

                await Actor.push_data(page_new_leads)
                Actor.log.info(
                    f"Page {page_num}: Added {len(page_new_leads)} leads (Total: {len(results)}/{max_results})"
                )

                # Handle Next Page
                next_form = soup.select_one(
                    "form[action='/lite/'], form.nav-link, .nav-link form"
                )
                if not next_form:
                    Actor.log.info("Reached end of search results.")
                    break

                next_data = {}
                for input_tag in next_form.select("input"):
                    name = input_tag.get("name")
                    value = input_tag.get("value", "")
                    if name:
                        next_data[name] = value

                if not next_data or next_data == form_data:
                    break

                form_data = next_data
                page_num += 1
                await asyncio.sleep(1.2)

            except Exception as e:
                Actor.log.error(f"Error on page {page_num}: {str(e)}")
                break

    return results


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Tractor Parts")
        city = actor_input.get("city", "Indore")
        max_results = int(actor_input.get("max_results", 100))

        proxy_url = None
        try:
            proxy_configuration = await Actor.create_proxy_configuration()
            if proxy_configuration:
                proxy_url = await proxy_configuration.new_url()
        except Exception:
            pass

        Actor.log.info(f"Starting extraction for '{keyword}' in '{city}'...")
        leads = await extract_indiamart_leads(keyword, city, max_results, proxy_url)

        if leads:
            Actor.log.info(f"Extraction successful: {len(leads)} leads saved.")
        else:
            Actor.log.warning("No leads found.")


if __name__ == "__main__":
    asyncio.run(main())
