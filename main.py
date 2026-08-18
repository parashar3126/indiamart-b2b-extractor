import asyncio
import re
from urllib.parse import quote_plus, unquote
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}


def clean_lead_data(
    raw_title: str, raw_snippet: str, actual_url: str, keyword: str, city: str
):
    # Clean company / product name
    clean_name = re.sub(r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE)
    clean_name = re.sub(
        r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Wholesaler|Retailer|Trader|Stockist|Distributor)\s+in.*$",
        "",
        clean_name,
        flags=re.IGNORECASE,
    ).strip()

    if not clean_name or len(clean_name) < 3:
        clean_name = raw_title

    # Extract 10-digit Indian Mobile Number
    phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", raw_snippet + " " + raw_title)
    phone = phone_match.group(0) if phone_match else "Available on profile"

    # Extract Price
    price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", raw_snippet)
    price = price_match.group(0) if price_match else "Price on Inquiry"

    return {
        "company_or_product": clean_name,
        "phone": phone,
        "price": price,
        "city": city if city else "All India",
        "indiamart_url": actual_url,
        "details": (
            raw_snippet
            if raw_snippet
            else f"{clean_name} supplier in {city or 'India'}"
        ),
    }


async def scrape_bing_indiamart(
    client: httpx.AsyncClient,
    keyword: str,
    city: str,
    max_results: int,
    seen_urls: set,
    seen_names: set,
):
    """Fetches high-volume leads using 50-results-per-page Bing engine."""
    results = []
    clean_k = keyword.replace('"', "").strip()
    clean_c = city.replace('"', "").strip() if city else ""

    query = f"site:indiamart.com {clean_k} {clean_c}".strip()
    Actor.log.info(f"[Engine 1: High-Volume Search] Query: '{query}'")

    for offset in range(1, max_results + 50, 50):
        if len(results) >= max_results:
            break

        url = (
            f"https://www.bing.com/search?q={quote_plus(query)}&count=50&first={offset}"
        )
        try:
            resp = await client.get(url, headers=HEADERS, timeout=20.0)
            if resp.status_code != 200:
                Actor.log.warning(
                    f"Bing returned status {resp.status_code} at offset {offset}"
                )
                break

            soup = BeautifulSoup(resp.text, "lxml")
            items = soup.select(".b_algo")
            if not items:
                Actor.log.info(f"End of Bing index at offset {offset}.")
                break

            batch = []
            for item in items:
                title_el = item.select_one("h2 a")
                if not title_el:
                    continue

                url_val = title_el.get("href", "")
                if "indiamart.com" not in url_val or url_val in seen_urls:
                    continue

                snippet_el = item.select_one(".b_caption p, .b_algoSlug")
                raw_snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                raw_title = title_el.get_text(strip=True)

                lead = clean_lead_data(raw_title, raw_snippet, url_val, keyword, city)
                norm_name = lead["company_or_product"].lower()

                if norm_name in seen_names:
                    continue

                seen_urls.add(url_val)
                seen_names.add(norm_name)
                batch.append(lead)
                results.append(lead)

                if len(results) >= max_results:
                    break

            if batch:
                await Actor.push_data(batch)
                Actor.log.info(
                    f"[Engine 1] Scraped {len(batch)} new leads from offset {offset} (Total: {len(results)}/{max_results})"
                )

            await asyncio.sleep(1.0)

        except Exception as e:
            Actor.log.warning(f"Bing Scraping error at offset {offset}: {e}")
            break

    return results


async def scrape_direct_indiamart_search(
    client: httpx.AsyncClient,
    keyword: str,
    city: str,
    max_results: int,
    seen_urls: set,
    seen_names: set,
):
    """Direct IndiaMART directory query fallback."""
    results = []
    clean_k = quote_plus(keyword.strip())
    clean_c = quote_plus(city.strip()) if city else ""

    direct_url = f"https://dir.indiamart.com/search.mp?ss={clean_k}&cq={clean_c}"
    Actor.log.info(f"[Engine 2: Direct IndiaMART] Querying: {direct_url}")

    try:
        resp = await client.get(direct_url, headers=HEADERS, timeout=20.0)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")

            # Extract listings from IndiaMART directory cards
            cards = soup.select(".card, .lst_cl, .r-cl, .listing-card")
            batch = []

            for card in cards:
                title_el = card.select_one(
                    ".to-be-titl, .gpName, .company-name, .cName, a[href*='indiamart.com']"
                )
                if not title_el:
                    continue

                url_val = title_el.get("href", "")
                if url_val.startswith("//"):
                    url_val = "https:" + url_val
                elif url_val.startswith("/"):
                    url_val = "https://www.indiamart.com" + url_val

                if "indiamart.com" not in url_val or url_val in seen_urls:
                    continue

                raw_title = title_el.get_text(strip=True)
                desc_el = card.select_one(".desc, .desc-txt, .specs, .product-desc")
                raw_snippet = (
                    desc_el.get_text(strip=True)
                    if desc_el
                    else card.get_text(" ", strip=True)[:200]
                )

                lead = clean_lead_data(raw_title, raw_snippet, url_val, keyword, city)
                norm_name = lead["company_or_product"].lower()

                if norm_name in seen_names:
                    continue

                seen_urls.add(url_val)
                seen_names.add(norm_name)
                batch.append(lead)
                results.append(lead)

                if len(results) >= max_results:
                    break

            if batch:
                await Actor.push_data(batch)
                Actor.log.info(
                    f"[Engine 2] Extracted {len(batch)} direct IndiaMART directory leads."
                )

    except Exception as e:
        Actor.log.warning(f"Direct IndiaMART scraper error: {e}")

    return results


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Tractor Parts")
        city = actor_input.get("city", "Indore")
        max_results = int(actor_input.get("max_results", 100))

        Actor.log.info(f"============================================================")
        Actor.log.info(f"Starting Bulk B2B Scraper: '{keyword}' in '{city}'")
        Actor.log.info(f"Target Lead Count: {max_results}")
        Actor.log.info(f"============================================================")

        proxy_url = None
        try:
            proxy_config = await Actor.create_proxy_configuration()
            if proxy_config:
                proxy_url = await proxy_config.new_url()
        except Exception:
            pass

        client_kwargs = {
            "headers": HEADERS,
            "timeout": 30.0,
            "follow_redirects": True,
        }
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        seen_urls = set()
        seen_names = set()
        all_leads = []

        async with httpx.AsyncClient(**client_kwargs) as client:
            # 1. First Pass: High-Volume Search Stream (50 results per batch)
            leads_bing = await scrape_bing_indiamart(
                client, keyword, city, max_results, seen_urls, seen_names
            )
            all_leads.extend(leads_bing)

            # 2. Second Pass: Direct IndiaMART Directory if target not reached
            if len(all_leads) < max_results:
                remaining = max_results - len(all_leads)
                Actor.log.info(
                    f"Fetching remaining {remaining} leads from Direct IndiaMART Directory..."
                )
                leads_direct = await scrape_direct_indiamart_search(
                    client, keyword, city, remaining, seen_urls, seen_names
                )
                all_leads.extend(leads_direct)

        if all_leads:
            Actor.log.info(
                f"🎉 SUCCESS! Total {len(all_leads)} high-quality B2B leads harvested into Dataset."
            )
        else:
            Actor.log.warning(
                "No leads found. Please check search keyword and city name."
            )


if __name__ == "__main__":
    asyncio.run(main())
