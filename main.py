import asyncio
import re
from urllib.parse import unquote, quote_plus
from apify import Actor
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def extract_leads_from_directory_html(
    html: str, default_city: str, seen_urls: set, seen_names: set
):
    """Deep extracts individual supplier cards from IndiaMART directory and catalog pages."""
    leads = []
    soup = BeautifulSoup(html, "lxml")

    # Match all supplier cards/listings on IndiaMART directory pages
    card_elements = soup.select(
        ".card, .lst_cl, .r-cl, .listing-card, .gACard, .prd-card, "
        "div[class*='card'], div[class*='listing'], div[class*='supplier']"
    )

    for card in card_elements:
        title_el = card.select_one(
            ".gpName, .company-name, .cName, .to-be-titl, h2 a, h3 a, a[href*='indiamart.com']"
        )
        if not title_el:
            continue

        raw_url = title_el.get("href", "")
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        elif raw_url.startswith("/"):
            raw_url = "https://www.indiamart.com" + raw_url

        if "buyer.indiamart.com" in raw_url or "javascript:" in raw_url:
            continue

        raw_title = title_el.get_text(strip=True)
        clean_name = re.sub(r"\s*-\s*IndiaMART.*$", "", raw_title, flags=re.IGNORECASE)
        clean_name = re.sub(
            r"(Manufacturers|Suppliers|Wholesale|Dealers|Exporters|Trader|Distributor)\s+in.*$",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip()

        norm_name = clean_name.lower().strip()
        if not clean_name or len(clean_name) < 3 or norm_name in seen_names:
            continue

        # Extract Snippet / Product Details
        desc_el = card.select_one(
            ".desc, .desc-txt, .specs, .product-desc, .snippet, p"
        )
        card_text = card.get_text(" ", strip=True)
        raw_snippet = desc_el.get_text(strip=True) if desc_el else card_text[:200]

        # Extract Phone
        phone_match = re.search(r"(\+91[-\s]?)?[6-9]\d{9}", card_text)
        phone = phone_match.group(0) if phone_match else "Available on profile"

        # Extract Price
        price_match = re.search(r"(₹\s*[\d,]+|Rs\.?\s*[\d,]+)", card_text)
        price = price_match.group(0) if price_match else "Price on Inquiry"

        # Extract Location / City
        city_el = card.select_one(".city, .cityName, .loc, .address, .city-name")
        found_city = city_el.get_text(strip=True) if city_el else default_city

        seen_names.add(norm_name)
        if raw_url:
            seen_urls.add(raw_url)

        leads.append(
            {
                "company_or_product": clean_name,
                "phone": phone,
                "price": price,
                "city": found_city if found_city else (default_city or "All India"),
                "indiamart_url": raw_url if raw_url else "https://www.indiamart.com",
                "details": raw_snippet,
            }
        )

    return leads


async def collect_directory_urls(client: httpx.AsyncClient, keyword: str, city: str):
    """Collects all IndiaMART category and city index URLs via search queries."""
    clean_k = keyword.replace('"', "").strip()
    clean_c = city.replace('"', "").strip() if city else ""

    queries = [
        f"site:dir.indiamart.com {clean_k} {clean_c}",
        f"site:indiamart.com {clean_k} {clean_c}",
        f"site:indiamart.com/company/ {clean_k} {clean_c}",
        f"site:indiamart.com {clean_k} suppliers {clean_c}",
        f"site:indiamart.com {clean_k} manufacturers {clean_c}",
        f"site:indiamart.com {clean_k} wholesale {clean_c}",
    ]

    found_urls = []
    seen_search_urls = set()

    for q in queries:
        try:
            resp = await client.post(
                "https://lite.duckduckgo.com/lite/", data={"q": q, "kl": "in-en"}
            )
            if resp.status_code != 200:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/", data={"q": q}
                )

            soup = BeautifulSoup(resp.text, "lxml")
            for a_tag in soup.select(".result-link, .result__a"):
                href = a_tag.get("href", "")
                if "uddg=" in href:
                    m = re.search(r"uddg=([^&]+)", href)
                    if m:
                        href = unquote(m.group(1))

                if (
                    "indiamart.com" in href
                    and "buyer.indiamart.com" not in href
                    and href not in seen_search_urls
                ):
                    seen_search_urls.add(href)
                    found_urls.append(href)

            await asyncio.sleep(0.8)
        except Exception:
            continue

    # Also directly append IndiaMART city directory URL
    direct_dir_url = f"https://dir.indiamart.com/search.mp?ss={quote_plus(clean_k)}&cq={quote_plus(clean_c)}"
    found_urls.insert(0, direct_dir_url)

    return found_urls


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        keyword = actor_input.get("keyword", "Tractor Parts")
        city = actor_input.get("city", "Indore")
        max_results = int(actor_input.get("max_results", 100))

        Actor.log.info(
            f"Target: Extracting full B2B leads for '{keyword}' in '{city}' (Target: {max_results})"
        )

        proxy_url = None
        try:
            proxy_config = await Actor.create_proxy_configuration()
            if proxy_config:
                proxy_url = await proxy_config.new_url()
        except Exception:
            pass

        client_kwargs = {
            "headers": HEADERS,
            "timeout": 25.0,
            "follow_redirects": True,
        }
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        seen_urls = set()
        seen_names = set()
        total_leads = []

        async with httpx.AsyncClient(**client_kwargs) as client:
            Actor.log.info(
                "Harvesting IndiaMART category & supplier directory pages..."
            )
            directory_urls = await collect_directory_urls(client, keyword, city)
            Actor.log.info(
                f"Found {len(directory_urls)} IndiaMART directories. Deep scraping supplier listings..."
            )

            for idx, page_url in enumerate(directory_urls, 1):
                if len(total_leads) >= max_results:
                    break

                Actor.log.info(
                    f"[{idx}/{len(directory_urls)}] Deep scraping: {page_url}"
                )
                try:
                    resp = await client.get(page_url, timeout=20.0)
                    if resp.status_code != 200:
                        continue

                    # Extract all cards from directory page
                    extracted = extract_leads_from_directory_html(
                        resp.text, city, seen_urls, seen_names
                    )

                    if extracted:
                        batch = []
                        for lead in extracted:
                            if len(total_leads) >= max_results:
                                break
                            batch.append(lead)
                            total_leads.append(lead)

                        await Actor.push_data(batch)
                        Actor.log.info(
                            f"Extracted {len(batch)} suppliers from page {idx}. Total: {len(total_leads)}/{max_results}"
                        )

                    await asyncio.sleep(1.0)

                except Exception as err:
                    Actor.log.warning(f"Error scraping {page_url}: {err}")
                    continue

        if total_leads:
            Actor.log.info(
                f"SUCCESS: Harvested {len(total_leads)} individual suppliers and shops into Dataset."
            )
        else:
            Actor.log.warning("No leads could be extracted.")


if __name__ == "__main__":
    asyncio.run(main())
