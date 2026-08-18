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


def parse_page_results(soup: BeautifulSoup, keyword: str, city: str, seen_urls: set, seen_names: set):
    page_leads = []

    # 1. Parse Standard HTML (.result)
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

        if actual_url in seen_urls or "indiamart.com" not in actual_url:
            continue

        raw_title = title_elem.get_text(strip=True)
        raw_snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        clean_name = re.sub(r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE)
        clean_name = re.sub(
            r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer|Trader)\s+in.*$",
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

        page_leads.append({
            "company_or_product": clean_name,
            "phone": phone,
            "price": price,
            "city": city if city else "All India",
            "indiamart_url": actual_url,
            "details": raw_snippet,
        })

    # 2. Parse Lite HTML (.result-link)
    for a_tag in soup.select(".result-link"):
        href = a_tag.get("href", "")
        actual_url = href
        if "uddg=" in href:
            match = re.search(r"uddg=([^&]+)", href)
            if match:
                actual_url = unquote(match.group(1))

        if actual_url in seen_urls or "indiamart.com" not in actual_url:
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

        clean_name = re.sub(r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE)
        clean_name = re.sub(
            r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer|Trader)\s+in.*$",
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

        page_leads.append({
            "company_or_product": clean_name,
            "phone": phone,
            "price": price,
            "city": city if city else "All India",
            "indiamart_url": actual_url,
            "details": raw_snippet,
        })

    return page_leads


def generate_search_queries(keyword: str, city: str):
    clean_k = keyword.replace('"', '').strip()
    clean_c = city.replace('"', '').strip() if city else ""

    if clean_c:
        return [
            f"site:indiamart.com {clean_k} {clean_c}",
            f"site:indiamart.com {clean_k} suppliers in {clean_c}",
            f"site:indiamart.com {clean_k} manufacturers {clean_c}",
            f"site:indiamart.com {clean_k} wholesale dealer {clean_c}",
            f"site:indiamart.com {clean_k} contact phone {clean_c}",
            f"site:indiamart.com {clean_k} distributors {clean_c}",
        ]
    else:
        return [
            f"site:indiamart.com {clean_k}",
            f"site:indiamart.com {clean_k} manufacturers India",
            f"site:indiamart.com {clean_k} wholesale suppliers",
            f"site:indiamart.com {clean_k} exporters dealers",
            f"site:indiamart.com {clean_k} contact price list",
        ]


async def extract_indiamart_leads(keyword: str, city: str, max_results: int, proxy_url: str = None):
    results = []
    seen_urls = set()
    seen_names = set()

    queries = generate_search_queries(keyword, city)
    Actor.log.info(f"Generated {len(queries)} B2B search streams for '{keyword}'. Target: {max_results} leads.")

    client_kwargs = {
        "headers": HEADERS,
        "timeout": 25.0,
        "follow_redirects": True,
    }
    if proxy_url:
        client_kwargs["proxy"] = proxy_url

    async with httpx.AsyncClient(**client_kwargs) as client:
        for q_idx, q in enumerate(queries, 1):
            if len(results) >= max_results:
                break

            Actor.log.info(f"Running search stream [{q_idx}/{len(queries)}]: {q}")

            # Try page offsets (0, 30, 60) for each query stream
            for offset in [0, 30, 60]:
                if len(results) >= max_results:
                    break

                try:
                    payload = {"q": q, "kl": "in-en"}
                    if offset > 0:
                        payload["s"] = str(offset)
                        payload["next"] = "Next Page"

                    response = await client.post("https://lite.duckduckgo.com/lite/", data=payload)

                    if response.status_code != 200 or len(response.text) < 400:
                        response = await client.get("https://html.duckduckgo.com/html/", params={"q": q})

                    soup = BeautifulSoup(response.text, "lxml")
                    new_leads = parse_page_results(soup, keyword, city, seen_urls, seen_names)

                    if not new_leads:
                        break

                    for lead in new_leads:
                        if len(results) >= max_results:
                            break
                        results.append(lead)

                    await Actor.push_data(new_leads)
                    Actor.log.info(f"Stream {q_idx} (Offset {offset}): Added {len(new_leads)} unique leads. (Total: {len(results)}/{max_results})")

                    await asyncio.sleep(1.0)

                except Exception as e:
                    Actor.log.warning(f"Stream {q_idx} error: {e}")
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

        Actor.log.info(f"Starting Multi-Stream Extractor for '{keyword}' in '{city}' (Target: {max_results})...")
        leads = await extract_indiamart_leads(keyword, city, max_results, proxy_url)

        if leads:
            Actor.log.info(f"Job completed successfully. Total unique leads: {len(leads)}")
        else:
            Actor.log.warning("No leads found.")


if __name__ == "__main__":
    asyncio.run(main())