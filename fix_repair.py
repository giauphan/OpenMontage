import re

def test():
    body = "var tl = gsap.timeline({paused: true});"
    tl_decl = re.search(r"(?:const|let|var)\s+tl\s*=[^;]+;", body)
    print(bool(tl_decl))

test()
