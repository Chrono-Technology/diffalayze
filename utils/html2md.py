import pathlib
import argparse
from bs4 import BeautifulSoup
from markdownify import markdownify as md


def remove_legends_tables(soup: BeautifulSoup) -> None:
    for table in soup.find_all("table"):
        previous = table.find_previous_sibling()
        if previous and previous.name == "p" and "Legends" in previous.get_text():
            previous.decompose()
            table.decompose()
        elif table.find("td") and "Legends" in table.get_text():
            table.decompose()


def html_to_markdown(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")

    for tag in soup.find_all(["style", "script"]):
        tag.decompose()

    remove_legends_tables(soup)

    markdown = md(str(soup), heading_style="ATX")

    markdown = "\n".join(line.rstrip() for line in markdown.splitlines())
    return markdown


def convert_file(input_path: str, output_path: str = None) -> str:
    html_text = pathlib.Path(input_path).read_text(encoding="utf-8")
    markdown = html_to_markdown(html_text)

    if output_path:
        pathlib.Path(output_path).write_text(markdown, encoding="utf-8")
    return markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Ghidriff HTML sxs to markdown converter")
    parser.add_argument("input_html", help="Input file (HTML)")
    parser.add_argument("-o", "--output", help="Output file (MD)")
    args = parser.parse_args()

    markdown = convert_file(args.input_html, args.output)

    if not args.output:
        print(markdown)


if __name__ == "__main__":
    main()

