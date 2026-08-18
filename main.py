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


def parse_page_results(soup: BeautifulSoup, city: str, seen_urls: set, seen_names: set):
    page_leads = []

    # 1. Parse DuckDuckGo Lite Link Elements
    link_elements = soup.select(".result-link")
    for a_tag in link_elements:
        href = a_tag.get("href", "")
        actual_url = href

        if "uddg=" in href:
            match = re.search(r"uddg=([^&]+)", href)
            if match:
                actual_url = unquote(match.group(1))

        # Only accept valid IndiaMART URLs
        if (
            not actual_url
            or "indiamart.com" not in actual_url
            or actual_url in seen_urls
        ):
            continue

        raw_title = a_tag.get_text(strip=True)
        parent_tr = a_tag.find_parent("tr")
        raw_snippet = ""
        if parent_tr:
            next_tr = parent_tr.find_next_sibling("tr")
            if next_tr:
                snippet_td = next_tr.select_one(".result-snippet")
                if snippet_td:
                    raw_snippet = snippet_td.get_text(strip=True)

        # Clean Company / Product Name
        clean_name = re.sub(r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE)
        clean_name = re.sub(
            r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer|Trader|Stockist)\s+in.*$",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip()

        norm_name = clean_name.lower().strip()
        if not clean_name or len(clean_name) < 3 or norm_name in seen_names:
            continue

        seen_urls.add(actual_url)
        seen_names.add(norm_name)

        # Extract Indian Mobile Number
        phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet)
        phone = phone_match.group(0) if phone_match else "Available on profile"

        # Extract Price Details
        price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
        price = price_match.group(0) if price_match else "Price on Inquiry"

        page_leads.append(
            {
                "company_or_product": clean_name,
                "phone": phone,
                "price": price,
                "city": city if city else "All India",
                "indiamart_url": actual_url,
                "details": raw_snippet,
            }
        )

    # 2. Fallback parse for Standard HTML results (.result)
    if not page_leads:
        for item in soup.select(".result"):
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

            if (
                not actual_url
                or "indiamart.com" not in actual_url
                or actual_url in seen_urls
            ):
                continue

            raw_title = title_elem.get_text(strip=True)
            raw_snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

            clean_name = re.sub(
                r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE
            )
            clean_name = re.sub(
                r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer|Trader|Stockist)\s+in.*$",
                "",
                clean_name,
                flags=re.IGNORECASE,
            ).strip()

            norm_name = clean_name.lower().strip()
            if not clean_name or len(clean_name) < 3 or norm_name in seen_names:
                continue

            seen_urls.add(actual_url)
            seen_names.add(norm_name)

            phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet)
            phone = phone_match.group(0) if phone_match else "Available on profile"

            price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
            price = price_match.group(0) if price_match else "Price on Inquiry"

            page_leads.append(
                {
                    "company_or_product": clean_name,
                    "phone": phone,
                    "price": price,
                    "city": city if city else "All India",
                    "indiamart_url": actual_url,
                    "details": raw_snippet,
                }
            )

    return page_leads


def generate_search_streams(keyword: str, city: str):
    clean_k = keyword.replace('"', "").strip()
    clean_c = city.replace('"', "").strip() if city else ""

    if clean_c:
        return [
            f"site:indiamart.com {clean_k} {clean_c}",
            f"site:indiamart.com/company/ {clean_k} {clean_c}",
            f"site:indiamart.com/proddetail/ {clean_k} {clean_c}",
            f"site:indiamart.com {clean_k} suppliers {clean_c}",
            f"site:indiamart.com {clean_k} manufacturers {clean_c}",
            f"site:indiamart.com {clean_k} dealers {clean_c}",
        ]
    else:
        return [
            f"site:indiamart.com {clean_k}",
            f"site:indiamart.com/company/ {clean_k}",
            f"site:indiamart.com/proddetail/ {clean_k}",
            f"site:indiamart.com {clean_k} wholesale manufacturers India",
            f"site:indiamart.com {clean_k} suppliers exporters",
        ]


async def extract_indiamart_leads(
    keyword: str, city: str, max_results: int, proxy_url: str = None
):
    results = []
    seen_urls = set()
    seen_names = set()

    search_streams = generate_search_streams(keyword, city)
    Actor.log.info(
        f"Generated {len(search_streams)} parallel B2B search streams for '{keyword}'. Target: {max_results} leads."
    )

    client_kwargs = {
        "headers": HEADERS,
        "timeout": 30.0,
        "follow_redirects": True,
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        for s_idx, query in enumerate(search_streams, 1):
            if len(results) >= max_results:
                break

            Actor.log.info(
                f"--- Running Stream [{s_idx}/{len(search_streams)}]: '{query}' ---"
            )
            current_url = "https://lite.duckduckgo.com/lite/"
            current_payload = {"q": query, "kl": "in-en"}
            page_in_stream = 1

            while len(results) < max_results and page_in_stream <= 4:
                try:
                    Actor.log.info(
                        f"Stream {s_idx} -> Fetching Page {page_in_stream}..."
                    )
                    response = await client.post(
                        current_url, data=current_payload, headers=HEADERS
                    )

                    if response.status_code != 200 or len(response.text) < 400:
                        Actor.log.warning(
                            f"Status {response.status_code} on Stream {s_idx}. Switching stream..."
                        )
                        break

                    soup = BeautifulSoup(response.text, "lxml")
                    new_leads = parse_page_results(soup, city, seen_urls, seen_names)

                    if not new_leads:
                        Actor.log.info(f"No more leads in Stream {s_idx}.")
                        break

                    for lead in new_leads:
                        if len(results) >= max_results:
                            break
                        results.append(lead)

                    await Actor.push_data(new_leads)
                    Actor.log.info(
                        f"Stream {s_idx} [Page {page_in_stream}]: +{len(new_leads)} leads added. (Total: {len(results)}/{max_results})"
                    )

                    if len(results) >= max_results:
                        break

                    # Extract actual token form for Next Page
                    next_form = soup.select_one(
                        "form[action='/lite/'], form.nav-link, .nav-link form"
                    )
                    if not next_form:
                        Actor.log.info(f"Stream {s_idx}: Reached last page.")
                        break

                    next_payload = {}
                    for input_tag in next_form.select("input"):
                        name = input_tag.get("name")
                        val = input_tag.get("value", "")
                        if name:
                            next_payload[name] = val

                    if not next_payload or next_payload == current_payload:
                        break

                    current_payload = next_payload
                    page_in_stream += 1
                    await asyncio.sleep(1.2)

                except Exception as err:
                    Actor.log.warning(
                        f"Error in Stream {s_idx} Page {page_in_stream}: {err}"
                    )
                    break

            await asyncio.sleep(1.0)

    return results


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Tractor Parts")
        city = actor_input.get("city", "Indore")
        max_results = int(actor_input.get("max_results", 50))

        proxy_url = None
        try:
            proxy_config = await Actor.create_proxy_configuration()
            if proxy_config:
                proxy_url = await proxy_config.new_url()
        except Exception:
            pass

        Actor.log.info(
            f"Starting Multi-Stream Extractor for '{keyword}' in '{city}' with target {max_results}..."
        )
        leads = await extract_indiamart_leads(keyword, city, max_results, proxy_url)

        if leads:
            Actor.log.info(
                f"Scraping Completed! Successfully harvested {len(leads)} leads into Dataset."
            )
        else:
            Actor.log.warning("No leads found. Please check query keywords.")


if __name__ == "__main__":
    asyncio.run(main())
