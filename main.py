import asyncio
import re
from urllib.parse import unquote
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def build_query_variations(keyword: str, city: str):
    k = keyword.strip()
    c = city.strip() if city else ""

    variations = [
        f"site:indiamart.com {k} {c}",
        f"site:indiamart.com {k} suppliers {c}",
        f"site:indiamart.com {k} manufacturers {c}",
        f"site:indiamart.com {k} dealers {c}",
        f"site:indiamart.com {k} wholesale {c}",
        f"site:indiamart.com {k} spare parts {c}",
        f"site:indiamart.com {k} distributors {c}",
        f"site:indiamart.com {k} traders {c}",
        f"site:indiamart.com {k} retail shop {c}",
        f"site:indiamart.com/company/ {k} {c}",
        f"site:indiamart.com/proddetail/ {k} {c}",
        f"site:indiamart.com {k} contact phone {c}",
    ]
    return [v.strip() for v in variations]


def parse_leads_from_html(
    html_content: str, city: str, seen_urls: set, seen_names: set
):
    leads = []
    soup = BeautifulSoup(html_content, "lxml")

    # DuckDuckGo HTML / Lite parser
    entries = soup.select(".result, .result-link")

    # If standard result cards exist
    results = soup.select(".result")
    if results:
        for item in results:
            title_el = item.select_one(".result__title .result__a")
            snippet_el = item.select_one(".result__snippet")
            if not title_el:
                continue

            raw_url = title_el.get("href", "")
            if "uddg=" in raw_url:
                m = re.search(r"uddg=([^&]+)", raw_url)
                if m:
                    raw_url = unquote(m.group(1))

            if "indiamart.com" not in raw_url or raw_url in seen_urls:
                continue

            raw_title = title_el.get_text(strip=True)
            raw_snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # Clean Name
            name = re.sub(r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE)
            name = re.sub(
                r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Trader|Distributor)\s+in.*$",
                "",
                name,
                flags=re.IGNORECASE,
            ).strip()
            norm = name.lower().strip()

            if not name or len(name) < 3 or norm in seen_names:
                continue

            seen_urls.add(raw_url)
            seen_names.add(norm)

            phone_match = re.search(
                r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet + " " + raw_title
            )
            phone = phone_match.group(0) if phone_match else "Available on profile"

            price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
            price = price_match.group(0) if price_match else "Price on Inquiry"

            leads.append(
                {
                    "company_or_product": name,
                    "phone": phone,
                    "price": price,
                    "city": city if city else "All India",
                    "indiamart_url": raw_url,
                    "details": (
                        raw_snippet if raw_snippet else f"{name} listed on IndiaMART"
                    ),
                }
            )

    # Lite view fallback
    lite_links = soup.select(".result-link")
    if lite_links and not leads:
        for a_tag in lite_links:
            raw_url = a_tag.get("href", "")
            if "uddg=" in raw_url:
                m = re.search(r"uddg=([^&]+)", raw_url)
                if m:
                    raw_url = unquote(m.group(1))

            if "indiamart.com" not in raw_url or raw_url in seen_urls:
                continue

            raw_title = a_tag.get_text(strip=True)
            parent_tr = a_tag.find_parent("tr")
            raw_snippet = ""
            if parent_tr:
                next_tr = parent_tr.find_next_sibling("tr")
                if next_tr:
                    snip_td = next_tr.select_one(".result-snippet")
                    if snip_td:
                        raw_snippet = snip_td.get_text(strip=True)

            name = re.sub(
                r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE
            ).strip()
            norm = name.lower().strip()

            if not name or len(name) < 3 or norm in seen_names:
                continue

            seen_urls.add(raw_url)
            seen_names.add(norm)

            phone_match = re.search(
                r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet + " " + raw_title
            )
            phone = phone_match.group(0) if phone_match else "Available on profile"

            price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
            price = price_match.group(0) if price_match else "Price on Inquiry"

            leads.append(
                {
                    "company_or_product": name,
                    "phone": phone,
                    "price": price,
                    "city": city if city else "All India",
                    "indiamart_url": raw_url,
                    "details": (
                        raw_snippet if raw_snippet else f"{name} listed on IndiaMART"
                    ),
                }
            )

    return leads


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Tractor Parts")
        city = actor_input.get("city", "Indore")
        max_results = int(actor_input.get("max_results", 100))

        Actor.log.info(
            f"Target: Extracting all '{keyword}' leads in '{city}' (Target: {max_results})"
        )

        queries = build_query_variations(keyword, city)
        seen_urls = set()
        seen_names = set()
        all_leads = []

        proxy_url = None
        try:
            proxy_config = await Actor.create_proxy_configuration()
            if proxy_config:
                proxy_url = await proxy_config.new_url()
        except Exception:
            pass

        client_kwargs = {"headers": HEADERS, "timeout": 25.0, "follow_redirects": True}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        async with httpx.AsyncClient(**client_kwargs) as client:
            for idx, q in enumerate(queries, 1):
                if len(all_leads) >= max_results:
                    break

                Actor.log.info(f"[{idx}/{len(queries)}] Scraping stream: {q}")
                try:
                    # Request HTML endpoint
                    resp = await client.post(
                        "https://html.duckduckgo.com/html/", data={"q": q}
                    )
                    if resp.status_code != 200:
                        resp = await client.post(
                            "https://lite.duckduckgo.com/lite/",
                            data={"q": q, "kl": "in-en"},
                        )

                    batch_leads = parse_leads_from_html(
                        resp.text, city, seen_urls, seen_names
                    )

                    if batch_leads:
                        valid_batch = []
                        for lead in batch_leads:
                            if len(all_leads) >= max_results:
                                break
                            valid_batch.append(lead)
                            all_leads.append(lead)

                        await Actor.push_data(valid_batch)
                        Actor.log.info(
                            f"Stream {idx} extracted {len(valid_batch)} new leads. Total: {len(all_leads)}/{max_results}"
                        )

                    await asyncio.sleep(1.0)

                except Exception as e:
                    Actor.log.warning(f"Error on stream {idx}: {e}")
                    continue

        if all_leads:
            Actor.log.info(
                f"DONE! Total {len(all_leads)} unique leads saved to dataset."
            )
        else:
            Actor.log.warning("No leads found.")


if __name__ == "__main__":
    asyncio.run(main())
