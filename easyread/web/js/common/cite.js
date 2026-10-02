/* 引用只使用已有元数据，格式化与批量排序都不访问网络。 */
(function (PR) {
  "use strict";
  const text = (v) => v == null ? "" : String(v).trim();
  const authors = (i) => text(i.authors).split(",").map(text).filter(Boolean);
  const title = (i) => text(i.title_en) || text(i.title_zh);
  const chinese = (s) => /\p{Script=Han}/u.test(s);
  const surname = (name) => chinese(name) ? name : name.split(/\s+/).pop();
  const arxiv = (i) => text(i.arxiv).replace(/^arxiv:\s*/i, "").split(/\s/)[0];
  const source = (i) => text(i.venue) || (arxiv(i) ? "arXiv:" + arxiv(i) : "");
  const sentence = (s) => s ? s + (/[.!?]$/.test(s) ? "" : ".") : "";

  PR.citeType = function (i) {
    const venue = text(i.venue);
    if (/\b(conference|proceedings|workshop|symposium|neurips|icml|iclr|acl|emnlp|naacl|cvpr|iccv|eccv|aaai|ijcai|kdd|sigir|www|chi)\b/i.test(venue)) return "conference";
    return !venue && arxiv(i) ? "preprint" : "journal";
  };

  function citeKey(i) {
    const latin = (s) => s.normalize("NFKD").replace(/[^A-Za-z]/g, "").toLowerCase();
    const last = latin(surname(authors(i)[0] || "anon")) || "anon";
    const word = title(i).split(/\s+/).find((w) => w.length > 3 && latin(w)) || "paper";
    return last + text(i.year).replace(/[^0-9A-Za-z]/g, "") + latin(word);
  }

  function authorName(name, apa) {
    if (chinese(name)) return name;
    const parts = name.split(/\s+/), last = parts.pop();
    const initials = parts.map((p) => p.replace(/\./g, "").split("-").filter(Boolean).map((s) => s[0].toUpperCase() + (apa ? "." : "")).join("-")).join(" ");
    return (apa ? last : last.toUpperCase()) + (initials ? (apa ? ", " : " ") + initials : "");
  }

  // 同时转义字段中的花括号与反斜线，避免元数据破坏 BibTeX 结构。
  function bibEscape(value) {
    const escapes = { "\\": "\\textbackslash{}", "^": "\\textasciicircum{}", "~": "\\textasciitilde{}" };
    return text(value).replace(/[\\&%$#_{}^~]/g, (c) => escapes[c] || "\\" + c);
  }

  function bibtex(i, key) {
    const type = PR.citeType(i), fields = [
      "title = {{" + bibEscape(title(i)) + "}}",
      "author = {" + authors(i).map(bibEscape).join(" and ") + "}",
      "year = {" + bibEscape(i.year) + "}",
    ];
    if (text(i.venue)) fields.push((type === "conference" ? "booktitle" : "journal") + " = {" + bibEscape(i.venue) + "}");
    if (type === "preprint") fields.push("eprint = {" + bibEscape(arxiv(i)) + "}", "archivePrefix = {arXiv}");
    if (text(i.doi)) fields.push("doi = {" + bibEscape(i.doi) + "}");
    if (text(i.url)) fields.push("url = {" + bibEscape(i.url) + "}");
    return "@" + ({ journal: "article", conference: "inproceedings", preprint: "misc" }[type]) + "{" + key + ",\n  " + fields.join(",\n  ") + "\n}";
  }

  PR.cite = function (i, style) {
    if (style === "bibtex") return bibtex(i, citeKey(i));
    const names = authors(i);
    if (style === "apa") {
      const formatted = names.map((n) => authorName(n, true));
      const who = names.length > 20 ? formatted.slice(0, 19).join(", ") + ", … " + formatted[formatted.length - 1] :
        formatted.length > 1 ? formatted.slice(0, -1).join(", ") + ", & " + formatted[formatted.length - 1] : formatted[0] || "";
      return [who, "(" + (text(i.year) || "n.d.") + ").", sentence(title(i)), source(i) + (text(i.url) ? (source(i) ? ". " : "") + text(i.url) : "")].filter(Boolean).join(" ");
    }
    const who = names.slice(0, 3).map((n) => authorName(n, false)).join(", ") +
      (names.length > 3 ? (names.some(chinese) ? ", 等" : ", et al.") : ""); // i18n-ok：引用按作者语言生成，不跟随界面语言
    const marker = { journal: "J", conference: "C", preprint: "EB/OL" }[PR.citeType(i)];
    return [sentence(who), title(i) + "[" + marker + "].", sentence([source(i), text(i.year)].filter(Boolean).join(", ")), sentence(text(i.url))].filter(Boolean).join(" ");
  };

  PR.citeMissing = function (i, style) {
    const missing = [];
    if (!authors(i).length) missing.push(PR.t("作者"));
    if (!text(i.year)) missing.push(PR.t("年份"));
    if (!title(i)) missing.push(PR.t("题名"));
    if (style !== "bibtex" && !source(i)) missing.push(PR.t("出处"));
    return missing;
  };

  function compareAuthor(a, b, style) {
    const first = surname(authors(a)[0] || ""), second = surname(authors(b)[0] || "");
    if (style === "gb" && chinese(first) !== chinese(second)) return chinese(first) ? 1 : -1;
    return first.localeCompare(second, chinese(first) && chinese(second) ? "zh-CN-u-co-pinyin" : "en", { sensitivity: "base" }) || title(a).localeCompare(title(b), "en");
  }

  function suffix(n) {
    let out = "";
    do { out = String.fromCharCode(97 + n % 26) + out; n = Math.floor(n / 26) - 1; } while (n >= 0);
    return out;
  }

  PR.citeBatch = function (items, style) {
    if (style !== "bibtex") return items.slice().sort((a, b) => compareAuthor(a, b, style))
      .map((i, n) => (style === "gb" ? "[" + (n + 1) + "] " : "") + PR.cite(i, style)).join("\n\n");
    const keys = items.map(citeKey), counts = new Map(), used = new Set(keys), next = new Map();
    keys.forEach((key) => counts.set(key, (counts.get(key) || 0) + 1));
    return items.map((i, n) => {
      const base = keys[n];
      let key = base;
      if (counts.get(base) > 1) {
        let index = next.get(base) || 0;
        do { key = base + suffix(index++); } while (used.has(key));
        next.set(base, index); used.add(key);
      }
      return bibtex(i, key);
    }).join("\n\n");
  };
})(window.PR);
