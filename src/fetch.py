import requests
from bs4 import BeautifulSoup


def fetch_html(url="https://kiosken.tihlde.org"):
    response = requests.get(url)
    response.raise_for_status()
    return response.text


def parse_inventory(html):
    soup = BeautifulSoup(html, "html.parser")
    inventory = {}

    product_section = soup.find("div", class_="grid grid-cols-3 gap-3")
    if not product_section:
        print(
            "Warning: Could not find product grid. Possibly client-side rendered or layout changed."
        )
        return inventory

    product_entries = product_section.find_all(
        "div", class_="space-y-1 border-2 border-sky-700 rounded-lg p-2"
    )

    for entry in product_entries:
        count_tag = entry.find("p", class_="text-center font-semibold text-xl")
        name_tags = entry.find_all("p", class_="text-center")

        if count_tag and len(name_tags) > 1:
            try:
                count = int(count_tag.get_text(strip=True))
                name = name_tags[-1].get_text(strip=True)
                inventory[name] = count
            except ValueError:
                pass

    return inventory


def get_inventory():
    """
    High-level function that fetches HTML and then parses it.
    Returns a dictionary { product_name: count }.
    """
    html = fetch_html()
    return parse_inventory(html)


if __name__ == "__main__":
    inventory = get_inventory()
    print(inventory)
