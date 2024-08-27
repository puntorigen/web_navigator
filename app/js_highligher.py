highlight_js = """
() => {
    document.querySelectorAll("a,button,input,textarea").forEach((e) => {
        const attrs = e.attributes;
        const attrPairsP1 = [];
        const attrPairsP2 = [];
        const attrPairsP3 = [];
        for (let i = 0; i < attrs.length; i++) {
            const attr = attrs[i];
            const attrName = attr.name.trim();
            const attrValue = attr.value.trim();
            if (attrName.length === 0 || attrValue.length === 0) continue;

            switch (attrName) {
                case "id":
                    attrPairsP1.push(`${attrName}=${attrValue}`);
                    break;
                case "aria-label":
                case "title":
                    if (attrPairsP2.length === 0) {
                        if (attrValue !== e.innerText) {
                            attrPairsP2.push(`${attrName}=${attrValue}`);
                        }
                    }
                    break;
                case "class":
                    attrPairsP3.push(`${attrName}=${attrValue}`);
                    break;
            }
        }

        const attrPairs = [];
        if (attrPairsP1.length > 0) {
            attrPairs.push(...attrPairsP1);
        } else if (attrPairsP2.length > 0) {
            attrPairs.push(...attrPairsP2);
        } else {
            attrPairs.push(...attrPairsP3);
        }
        if (attrPairs.length === 0) return;

        const rect = e.getBoundingClientRect();
        const left = rect.left + window.scrollX;
        const top = rect.top + window.scrollY;

        const div = document.createElement("div");
        div.innerText = attrPairs.join(" ");
        div.style.cssText = `
            //background: rgba(0, 0, 0, 0.7);  /* Semi-translucent black */
            background: black;
            color: white;
            font-size: 12px;
            position: absolute;
            top: ${top - 12}px;
            left: ${left - 6}px;
            z-index: 2147483647;
        `;
        document.body.appendChild(div);
    });
}
"""
