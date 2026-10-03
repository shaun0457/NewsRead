/* Zotero's RDF importer honors z:itemType and native field names.
   BibTeX remains available for LaTeX; @misc alone cannot preserve Preprint.
   Format references: github.com/zotero/translators/{Zotero%20RDF,RDF}.js */
(function (PR) {
  "use strict";
  const text = v => v == null ? "" : String(v).trim();
  const xml = v => text(v).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\uFFFE\uFFFF]/g, "")
    .replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c]));
  const field = (name, value) => text(value) ? "    <" + name + ">" + xml(value) + "</" + name + ">\n" : "";
  function creator(name) {
    const parts = name.split(/\s+/), family = parts.pop();
    const values = /\p{Script=Han}/u.test(name) || !parts.length
      ? field("foaf:name", name)
      : field("foaf:surname", family) + field("foaf:givenName", parts.join(" "));
    return "      <rdf:li><foaf:Person>\n" + values + "      </foaf:Person></rdf:li>\n";
  }
  PR.citeZotero = function (items) {
    const header = '<?xml version="1.0" encoding="UTF-8"?>\n<rdf:RDF\n' +
      '  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n' +
      '  xmlns:bib="http://purl.org/net/biblio#"\n  xmlns:dc="http://purl.org/dc/elements/1.1/"\n' +
      '  xmlns:foaf="http://xmlns.com/foaf/0.1/"\n  xmlns:z="http://www.zotero.org/namespaces/export#">\n';
    return header + items.map((i, index) => {
      const type = PR.citeType(i), arxiv = text(i.arxiv).replace(/^arxiv:\s*/i, "").split(/\s/)[0];
      let out = '  <bib:Article rdf:about="urn:easyread:citation:' + index + '">\n' +
        field("z:itemType", { preprint: "preprint", conference: "conferencePaper", journal: "journalArticle" }[type]) +
        field("dc:title", i.title_en || i.title_zh) + field("dc:date", i.year) +
        field("z:url", i.url) + field("z:DOI", PR.normalizeDoi(i.doi));
      const names = text(i.authors).split(/,|\s+and\s+/i).map(text).filter(Boolean);
      if (names.length) out += "    <bib:authors><rdf:Seq>\n" + names.map(creator).join("") + "    </rdf:Seq></bib:authors>\n";
      if (type === "preprint") {
        out += field("z:repository", arxiv ? "arXiv" : i.venue) + field("z:archiveID", arxiv) +
          field("z:archive", arxiv ? "arXiv" : i.venue) + field("dc:coverage", arxiv);
      } else out += field(type === "conference" ? "z:proceedingsTitle" : "z:publicationTitle", i.venue);
      return out + "  </bib:Article>\n";
    }).join("") + "</rdf:RDF>\n";
  };
})(window.PR);
