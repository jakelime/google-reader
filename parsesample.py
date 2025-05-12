import re

from bs4 import BeautifulSoup

with open("sample.html", "r") as f:
    html = f.read()
    # print(html)


# soup = BeautifulSoup(html, "html.parser")
soup = BeautifulSoup(html, "html5lib")
label_text = "BILLED TO"
mystring = re.compile(r"\s*" + re.escape(label_text) + r"\s*", re.IGNORECASE)
print(f"{mystring=}")
# html5lib
# print(soup.prettify())

label_span = soup.find("span", string=mystring)


print(label_span)


label_text = "APPLE ACCOUNT"
mystring = re.compile(r"\s*" + re.escape(label_text) + r"\s*")
print(f"{mystring=}")
# html5lib
# print(soup.prettify())

label_span = soup.find("span", string=mystring)


print(label_span)
