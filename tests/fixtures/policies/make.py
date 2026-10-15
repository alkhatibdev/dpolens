"""Writes the Word test files: each one a pattern found in real policies, written from scratch.

Real policies never enter this repository, so every file here is invented and names no real
organisation. The files this writes are committed: the tests read the same files a reviewer
can open in Word. After changing a description here, write them again:

    uv run python tests/fixtures/policies/make.py

Every file is written the same way each time, so an unchanged description changes nothing.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
WRITTEN = (2026, 1, 1, 0, 0, 0)
target = HERE
"""Where the files go: here, or a folder a test compares with what is committed."""
NAMESPACES = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'mc:Ignorable="wps"'
)
RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml"

# Building blocks ----------------------------------------------------------------------------


def run(
    text: str,
    *,
    bold: bool = False,
    size: float | None = None,
    rtl: bool = False,
    caps: bool = False,
    hidden: bool = False,
) -> str:
    properties = ""
    if bold:
        properties += "<w:b/><w:bCs/>"
    if caps:
        properties += "<w:caps/>"
    if hidden:
        properties += "<w:vanish/>"
    if size is not None:
        half = int(size * 2)
        properties += f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/>'
    if rtl:
        properties += "<w:rtl/>"
    shaped = f"<w:rPr>{properties}</w:rPr>" if properties else ""
    return f'<w:r>{shaped}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def paragraph(
    text: str = "",
    *,
    style: str | None = None,
    numbered: tuple[int, int] | None = None,
    bold: bool = False,
    size: float | None = None,
    centre: bool = False,
    rtl: bool = False,
    caps: bool = False,
    runs: str | None = None,
) -> str:
    properties = ""
    if style:
        properties += f'<w:pStyle w:val="{style}"/>'
    if numbered:
        num_id, level = numbered
        properties += f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr>'
    if rtl:
        properties += "<w:bidi/>"
    if centre:
        properties += '<w:jc w:val="center"/>'
    if runs is None:
        runs = run(text, bold=bold, size=size, rtl=rtl, caps=caps) if text else ""
    return f"<w:p><w:pPr>{properties}</w:pPr>{runs}</w:p>"


def cell(*paragraphs: str, span: int = 1) -> str:
    merged = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
    inner = "".join(paragraphs) or paragraph()
    return f'<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/>{merged}</w:tcPr>{inner}</w:tc>'


def row(*cells: str, header: bool = False) -> str:
    repeated = "<w:trPr><w:tblHeader/></w:trPr>" if header else ""
    return f"<w:tr>{repeated}{''.join(cells)}</w:tr>"


def table(*rows: str, columns: int = 2) -> str:
    grid = "".join('<w:gridCol w:w="4000"/>' for _ in range(columns))
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(rows)}</w:tbl>"
    )


def text_cell(text: str, *, bold: bool = False, rtl: bool = False, span: int = 1) -> str:
    return cell(paragraph(text, bold=bold, rtl=rtl), span=span)


def definition(
    identifier: int,
    levels: list[tuple[str, str]],
    *,
    starts: dict[int, int] | None = None,
    legal: int | None = None,
    restart_never: int | None = None,
    link: str | None = None,
) -> str:
    """A list definition: each level's format and pattern, such as ("decimal", "%1.%2")."""
    if link is not None:
        return (
            f'<w:abstractNum w:abstractNumId="{identifier}"><w:multiLevelType w:val="multilevel"/>'
            f'<w:numStyleLink w:val="{link}"/></w:abstractNum>'
        )
    written = ""
    for level, (form, pattern) in enumerate(levels):
        start = (starts or {}).get(level, 1)
        extra = "<w:isLgl/>" if legal == level else ""
        if restart_never == level:
            extra += '<w:lvlRestart w:val="0"/>'
        written += (
            f'<w:lvl w:ilvl="{level}"><w:start w:val="{start}"/><w:numFmt w:val="{form}"/>'
            f'{extra}<w:lvlText w:val="{escape(pattern)}"/><w:lvlJc w:val="left"/></w:lvl>'
        )
    return (
        f'<w:abstractNum w:abstractNumId="{identifier}">'
        f'<w:multiLevelType w:val="multilevel"/>{written}</w:abstractNum>'
    )


def instance(identifier: int, definition_id: int, restarts: dict[int, int] | None = None) -> str:
    overrides = "".join(
        f'<w:lvlOverride w:ilvl="{level}"><w:startOverride w:val="{start}"/></w:lvlOverride>'
        for level, start in (restarts or {}).items()
    )
    return (
        f'<w:num w:numId="{identifier}"><w:abstractNumId w:val="{definition_id}"/>'
        f"{overrides}</w:num>"
    )


BULLETS = definition(90, [("bullet", "•"), ("bullet", "o")])
BULLET_LIST = instance(90, 90)

STYLES = """
<w:docDefaults>
<w:rPrDefault><w:rPr><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr/></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title">
<w:name w:val="Title"/><w:basedOn w:val="Normal"/>
<w:rPr><w:b/><w:bCs/><w:sz w:val="56"/><w:szCs w:val="56"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading1">
<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:bCs/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading2">
<w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/>{heading_list}<w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:bCs/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="Heading3">
<w:name w:val="heading 3"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:bCs/></w:rPr>
</w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph">
<w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720"/></w:pPr>
</w:style>
<w:style w:type="paragraph" w:styleId="TOCHeading">
<w:name w:val="TOC Heading"/><w:basedOn w:val="Heading1"/>
</w:style>
<w:style w:type="paragraph" w:styleId="TOC1">
<w:name w:val="toc 1"/><w:basedOn w:val="Normal"/>
</w:style>
"""


def package(
    name: str,
    body: str,
    *,
    numbering: str = "",
    styles: str = "",
    heading_list: int | None = None,
    **parts: str,
) -> None:
    """Write one .docx: a body, its list definitions, extra styles, and any other parts.

    `heading_list` numbers Heading 2 through its style, as a template's headings often are.
    """
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {NAMESPACES}><w:body>{body}<w:sectPr/></w:body></w:document>"
    )
    files = {"word/document.xml": document}
    files["word/styles.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:styles {NAMESPACES}>"
        + STYLES.replace(
            "{heading_list}",
            f'<w:numPr><w:numId w:val="{heading_list}"/></w:numPr>' if heading_list else "",
        )
        + f"{styles}</w:styles>"
    )
    targets = {"styles": "styles.xml"}
    if numbering:
        files["word/numbering.xml"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:numbering {NAMESPACES}>{numbering}</w:numbering>"
        )
        targets["numbering"] = "numbering.xml"
    for part, content in parts.items():
        files[f"word/{part}.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{content}'
        )
        targets[part] = f"{part}.xml"
    overrides = "".join(
        f'<Override PartName="/word/{target}" ContentType="{WORD}.{kind}+xml"/>'
        for kind, target in targets.items()
    )
    files["[Content_Types].xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/word/document.xml" ContentType="{WORD}.document.main+xml"/>'
        f"{overrides}</Types>"
    )
    files["_rels/.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{RELATIONSHIP}/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    files["word/_rels/document.xml.rels"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" Type="{RELATIONSHIP}/{kind}" Target="{target}"/>'
            for index, (kind, target) in enumerate(targets.items(), start=1)
        )
        + f'<Relationship Id="rId90" Type="{RELATIONSHIP}/hyperlink" '
        'Target="https://example.org/" TargetMode="External"/></Relationships>'
    )
    order = [
        "[Content_Types].xml",
        "_rels/.rels",
        *sorted(f for f in files if f.startswith("word")),
    ]
    with zipfile.ZipFile(target / name, "w") as written:
        for path in order:
            info = zipfile.ZipInfo(path, date_time=WRITTEN)
            info.compress_type = zipfile.ZIP_DEFLATED
            written.writestr(info, files[path])


def body(*blocks: str) -> str:
    return "".join(blocks)


# The files -----------------------------------------------------------------------------------


def heading_styles() -> None:
    """Heading 1 as the document's title over Heading 2 sections, a council's name above it,
    bullets under a lead-in, and one long sentence wrongly styled as a heading."""
    package(
        "heading-styles.docx",
        body(
            paragraph("THE COUNCIL", bold=True, centre=True),
            paragraph("Data Protection Policy", style="Heading1", centre=True),
            paragraph("Purpose of the policy", style="Heading2"),
            paragraph(
                "This policy explains to councillors, staff and the public how the Council "
                "looks after personal data."
            ),
            paragraph(
                "It applies to all personal data the Council holds, on paper or electronically."
            ),
            paragraph("Individuals’ rights", style="Heading2"),
            paragraph("The law gives individuals these rights:"),
            paragraph("the right to be informed", numbered=(90, 0)),
            paragraph("the right of access", numbered=(90, 0)),
            paragraph("the right to erasure", numbered=(90, 0)),
            paragraph(
                "The Clerk keeps a record of every request received and how it was answered, "
                "for at least three years.",
                style="Heading2",
            ),
            paragraph("Data breaches", style="Heading2"),
            paragraph("The Clerk investigates every data breach within 72 hours."),
        ),
        numbering=BULLETS + BULLET_LIST,
    )


def automatic_numbering() -> None:
    """No heading styles: automatic numbers 1., 1.1, 1.1.1 give the whole tree, bold marks the
    sections, a contents page is typed as a numbered list, and the policy's details table is
    printed again partway through, as in a document converted from a PDF."""
    details = table(
        row(text_cell("Policy name: Data Retention Policy"), text_cell("Policy number: 101")),
        row(text_cell("Approved: June 2026"), text_cell("Review: June 2028")),
    )
    package(
        "automatic-numbering.docx",
        body(
            paragraph("Data Retention Policy", style="Heading1", centre=True),
            paragraph("Contents", bold=True),
            paragraph("Introduction", numbered=(2, 0), bold=True),
            paragraph("Purpose and Scope", numbered=(2, 0), bold=True),
            paragraph("General Principles", numbered=(2, 0), bold=True),
            details,
            paragraph("Introduction", numbered=(1, 0), bold=True),
            paragraph(
                "A data retention policy is part of the life of personal data, from collection "
                "to disposal.",
                numbered=(1, 1),
            ),
            paragraph("Purpose and Scope", numbered=(1, 0), bold=True),
            paragraph("The purpose of this policy is to:", numbered=(1, 1)),
            paragraph("keep personal data no longer than it is needed", numbered=(90, 0)),
            paragraph("keep the records the law requires", numbered=(90, 0)),
            paragraph(
                "It applies to all staff, students and contractors who hold personal data.",
                numbered=(1, 1),
            ),
            details,
            paragraph("General Principles", numbered=(1, 0), bold=True),
            paragraph("Storage:", numbered=(1, 1)),
            paragraph(
                "A document should not be stored on paper and electronically at once.",
                numbered=(1, 2),
            ),
            paragraph("Speciﬁc retention periods are set in the schedule.", numbered=(1, 2)),
        ),
        numbering=(
            definition(1, [("decimal", "%1."), ("decimal", "%1.%2"), ("decimal", "%1.%2.%3")])
            + definition(2, [("decimal", "%1.")])
            + BULLETS
            + instance(1, 1)
            + instance(2, 2)
            + BULLET_LIST
        ),
    )


CONTENTS_FIELD = (
    '<w:sdt><w:sdtPr><w:docPartObj><w:docPartGallery w:val="Table of Contents"/>'
    "<w:docPartUnique/></w:docPartObj></w:sdtPr><w:sdtContent>"
    + paragraph("Contents", style="TOCHeading")
    + paragraph(
        runs=(
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run("1.\tOVERVIEW\t2")
        ),
        style="TOC1",
    )
    + paragraph(
        runs=run("2.\tPRINCIPLES\t2") + '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
        style="TOC1",
    )
    + "</w:sdtContent></w:sdt>"
)


def numbered_headings() -> None:
    """Heading 2 numbered by its style's list, a list that starts again at 1 inside a section,
    a Heading 2 left unnumbered among numbered ones, a Word contents page inside a content
    control, and a schedule table with a header row."""
    package(
        "numbered-headings.docx",
        body(
            paragraph("Data Protection and Privacy Policy", style="Title"),
            CONTENTS_FIELD,
            paragraph("OVERVIEW", style="Heading2"),
            paragraph("The Council is open about how it collects and uses personal data."),
            paragraph("PRINCIPLES", style="Heading2"),
            paragraph("The Council follows seven principles:"),
            paragraph("Lawfulness, fairness and transparency.", numbered=(5, 0)),
            paragraph("Purpose limitation.", numbered=(5, 0)),
            paragraph("Data minimisation.", numbered=(5, 0)),
            paragraph("DATA SECURITY", style="Heading2"),
            paragraph("The Council keeps personal data secure."),
            # Numbering switched off on this one heading, as real policies have it.
            paragraph("Paper Storage:", style="Heading2", numbered=(0, 0)),
            paragraph("Paper records are kept in a locked cabinet.", numbered=(90, 0)),
            paragraph("RETENTION SCHEDULE", style="Heading2"),
            table(
                row(
                    text_cell("DOCUMENT", bold=True),
                    text_cell("MINIMUM RETENTION PERIOD", bold=True),
                    text_cell("REASON", bold=True),
                    header=True,
                ),
                row(text_cell("Staff records"), text_cell("6 years"), text_cell("Employment law")),
                row(text_cell("Minutes"), text_cell("Indefinitely"), text_cell("Archive")),
                columns=3,
            ),
        ),
        numbering=(
            definition(4, [("decimal", "%1.")])
            + definition(5, [("decimal", "%1.")])
            + BULLETS
            + instance(4, 4)
            + instance(5, 5)
            + BULLET_LIST
        ),
        heading_list=4,
    )


def bold_headings() -> None:
    """No heading style anywhere: bold title lines, automatic numbers on bold sections, a
    second list inside a section, sub-sections with typed numbers, and a responsibilities
    table under a bold header row."""
    package(
        "bold-headings.docx",
        body(
            paragraph("General Policy Statement", bold=True, size=14),
            paragraph("Data Protection Policy", bold=True, size=14),
            paragraph("Objectives of the policy", numbered=(7, 0), bold=True, size=12),
            paragraph("To make sure that procedures for personal data are in place.", size=11),
            paragraph("The principles", numbered=(7, 0), bold=True, size=12),
            paragraph("Personal data shall be:", size=11),
            paragraph("Processed fairly and lawfully", numbered=(8, 0), size=11),
            paragraph("Obtained for specified purposes", numbered=(8, 0), size=11),
            paragraph("Policy principles", numbered=(7, 0), bold=True, size=12),
            paragraph("3.1 Fair collection", bold=True, size=12),
            paragraph("Individuals are told when their information is collected.", size=11),
            paragraph("3.2 Security", bold=True, size=12),
            paragraph("Access to personal data is limited to those who need it.", size=11),
            paragraph("Responsibilities", numbered=(7, 0), bold=True, size=12),
            table(
                row(text_cell("Who", bold=True), text_cell("What", bold=True)),
                row(text_cell("All staff"), text_cell("Follow this policy.")),
                row(text_cell("Line managers"), text_cell("Make sure their staff are trained.")),
            ),
        ),
        numbering=(
            definition(7, [("decimal", "%1.")])
            + definition(8, [("decimal", "%1.")])
            + instance(7, 7)
            + instance(8, 8)
        ),
    )


def typed_numbers() -> None:
    """Heading styles give the levels and numbers typed into the headings give the keys, under
    a title block and a metadata table, with a definitions table under a bold header."""
    package(
        "typed-numbers.docx",
        body(
            paragraph("DATA PROTECTION & PRIVACY POLICY", bold=True, size=26, centre=True),
            table(
                row(text_cell("Policy Owner", bold=True), text_cell("Office of the Rector")),
                row(text_cell("Version", bold=True), text_cell("1.0")),
            ),
            paragraph("1. Introduction", style="Heading1"),
            paragraph("Acme is committed to protecting the privacy of everyone it works with."),
            paragraph("2. Purpose and Scope", style="Heading1"),
            paragraph("2.1 Purpose", style="Heading2"),
            paragraph("This policy sets out how Acme handles personal data."),
            paragraph("2.2 Scope", style="Heading2"),
            paragraph("It applies to all employees and contractors."),
            paragraph("3. Key Definitions", style="Heading1"),
            table(
                row(text_cell("Term", bold=True), text_cell("Definition", bold=True)),
                row(
                    text_cell("Personal Data"),
                    text_cell("Any information relating to an identified person."),
                ),
                row(text_cell("Processing"), text_cell("Any operation performed on data.")),
            ),
        ),
    )


ARABIC_SECTIONS_NUMBERING = (
    definition(10, [("decimal", "%1-"), ("decimal", "%1-%2"), ("decimal", "%1-%2-%3")])
    + definition(11, [("none", "2-1")])
    + definition(12, [("none", "2-2")])
    + instance(10, 10)
    + instance(11, 10, {0: 1})
    + instance(12, 11)
    + instance(13, 12)
)

COVER_BOX = (
    '<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
    "<wps:wsp><wps:txbx><w:txbxContent>"
    + paragraph("أدخل شعار الجهة هنا.", rtl=True)
    + "</w:txbxContent></wps:txbx></wps:wsp></w:drawing></mc:Choice><mc:Fallback><w:pict>"
    "<v:shape><v:textbox><w:txbxContent>"
    + paragraph("أدخل شعار الجهة هنا.", rtl=True)
    + "</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>"
    "</mc:AlternateContent></w:r></w:p>"
)


def arabic_sections() -> None:
    """Unnumbered Heading 1 sections over automatic numbers written "1-", "1-1", "1-1-1" that
    start again in each section, two items whose labels are fixed text in one-item lists, a
    cover text box written twice (as a drawing and its fallback), and an approvals table."""
    package(
        "arabic-sections.docx",
        body(
            COVER_BOX,
            paragraph("سياسة الأمن السيبراني للبيانات", size=30, centre=True, rtl=True),
            table(
                row(
                    text_cell("الدور", bold=True, rtl=True), text_cell("الاسم", bold=True, rtl=True)
                ),
                row(text_cell("إعداد", rtl=True), text_cell("<اسم الموظف>", rtl=True)),
            ),
            paragraph("الغرض", style="Heading1", rtl=True),
            paragraph("تحدد هذه السياسة متطلبات حماية البيانات في <اسم الجهة>.", rtl=True),
            paragraph("بنود السياسة", style="Heading1", rtl=True),
            paragraph("البنود العامة", numbered=(10, 0), bold=True, rtl=True),
            paragraph("يجب أن تلتزم <اسم الجهة> بالمتطلبات التشريعية.", numbered=(10, 1), rtl=True),
            paragraph("يجب تصنيف البيانات في الصيغ التالية:", numbered=(10, 1), rtl=True),
            paragraph("الصيغ الرقمية.", numbered=(10, 2), rtl=True),
            paragraph("الصيغ الورقية.", numbered=(10, 2), rtl=True),
            paragraph("الاحتفاظ بالسجلات", numbered=(10, 0), bold=True, rtl=True),
            paragraph("يجب الاحتفاظ بسجل لعمليات الإتلاف.", numbered=(12, 0), rtl=True),
            paragraph("يجب تحديد مدة الاحتفاظ بالبيانات.", numbered=(13, 0), rtl=True),
            paragraph("الأدوار والمسؤوليات", style="Heading1", rtl=True),
            paragraph("مالك السياسة: <رئيس الإدارة المعنية>.", numbered=(11, 0), rtl=True),
            paragraph("تطبيق السياسة: <الإدارة المعنية>.", numbered=(11, 0), rtl=True),
        ),
        numbering=ARABIC_SECTIONS_NUMBERING,
    )


def requirements_table() -> None:
    """Requirements held in tables: a numbered title row, rows labelled "the objective" and
    "the risks", a row merged across the table, and requirement rows whose only number is an
    automatic one on an empty paragraph in the first column. The table is split in two, as
    Word does when a row's layout changes."""

    def numbered(num_id: int) -> str:
        return cell(paragraph(numbered=(num_id, 0), rtl=True))

    package(
        "requirements-table.docx",
        body(
            paragraph("المعايير", style="Heading1", rtl=True),
            table(
                row(numbered(20), text_cell("إدارة هويات الدخول والصلاحيات", rtl=True)),
                row(
                    text_cell("الهدف", rtl=True), text_cell("ضمان الوصول المصرح به فقط.", rtl=True)
                ),
                row(
                    text_cell("المخاطر المحتملة", rtl=True),
                    text_cell("وصول غير مصرح به.", rtl=True),
                ),
                row(text_cell("الإجراءات المطلوبة", bold=True, rtl=True, span=2)),
            ),
            table(
                row(
                    numbered(21),
                    text_cell("أن تستند الصلاحيات إلى مبدأ الحاجة إلى المعرفة.", rtl=True),
                ),
                row(numbered(21), text_cell("مراجعة حقوق الوصول دوريًا.", rtl=True)),
                row(numbered(20), text_cell("تشفير البيانات المنقولة", rtl=True)),
                row(
                    text_cell("الهدف", rtl=True), text_cell("حماية البيانات أثناء نقلها.", rtl=True)
                ),
                row(numbered(22), text_cell("استخدام التشفير عند نقل البيانات الحساسة.", rtl=True)),
            ),
        ),
        numbering=(
            definition(20, [("decimal", "%1")])
            + definition(21, [("decimal", "1-%1")])
            + definition(22, [("decimal", "2-%1")])
            + instance(20, 20)
            + instance(21, 21)
            + instance(22, 22)
        ),
    )


def word_constructs() -> None:
    """One paragraph for each place Word keeps text, so the coverage check can show that none
    of it is lost: every word below that is not deleted must reach a clause."""
    inserted = (
        '<w:ins w:id="1" w:author="Reviewer" w:date="2026-01-01T00:00:00Z">'
        + run("inserted")
        + "</w:ins>"
    )
    deleted = (
        '<w:del w:id="2" w:author="Reviewer" w:date="2026-01-01T00:00:00Z">'
        "<w:r><w:delText>deleted</w:delText></w:r></w:del>"
    )
    package(
        "word-constructs.docx",
        body(
            paragraph("Constructs", style="Heading1"),
            paragraph(
                runs=run("Hyperlinked ")
                + '<w:hyperlink r:id="rId90">'
                + run("text")
                + "</w:hyperlink>"
            ),
            paragraph(runs=run("Tracked ") + inserted + deleted),
            "<w:sdt><w:sdtPr/><w:sdtContent>"
            + paragraph("Block control text.")
            + "</w:sdtContent></w:sdt>",
            paragraph(
                runs=run("Inline ")
                + "<w:sdt><w:sdtPr/><w:sdtContent>"
                + run("control")
                + "</w:sdtContent></w:sdt>"
            ),
            paragraph(
                runs=run("Smart ")
                + '<w:smartTag w:uri="u" w:element="e">'
                + run("tag")
                + "</w:smartTag>"
            ),
            paragraph(
                runs=run("Simple ")
                + '<w:fldSimple w:instr="DOCPROPERTY Title">'
                + run("field")
                + "</w:fldSimple>"
            ),
            paragraph(
                runs=(
                    run("Complex ")
                    + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                    + '<w:r><w:instrText xml:space="preserve"> DATE </w:instrText></w:r>'
                    + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                    + run("result")
                    + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
                )
            ),
            paragraph(
                runs='<w:customXml w:element="x">' + run("Custom XML text.") + "</w:customXml>"
            ),
            paragraph(
                runs=run("Tab")
                + "<w:r><w:tab/></w:r>"
                + run("and break")
                + "<w:r><w:br/></w:r>"
                + run("here.")
            ),
            paragraph(runs=run("Symbol ") + '<w:r><w:sym w:font="Symbol" w:char="00B6"/></w:r>'),
            paragraph(runs=run("Hidden ") + run("text", hidden=True)),
            paragraph(
                runs=run("Noted")
                + '<w:r><w:footnoteReference w:id="1"/></w:r>'
                + '<w:r><w:commentReference w:id="0"/></w:r>'
            ),
            table(
                row(
                    "<w:sdt><w:sdtPr/><w:sdtContent>"
                    + text_cell("Cell in a control")
                    + "</w:sdtContent></w:sdt>",
                    text_cell("Plain cell"),
                ),
                row(text_cell("Second"), text_cell("Row")),
            ),
        ),
        comments=(
            f'<w:comments {NAMESPACES}><w:comment w:id="0" w:author="Reviewer">'
            + paragraph("A comment.")
            + "</w:comment></w:comments>"
        ),
        footnotes=(
            f'<w:footnotes {NAMESPACES}><w:footnote w:type="separator" w:id="-1"/>'
            '<w:footnote w:id="1">' + paragraph("A footnote.") + "</w:footnote></w:footnotes>"
        ),
    )


def size_headings() -> None:
    """Sub-headings marked only by larger type, a heading that asks a question in bold, and a
    body style that carries an outline level, as some templates' styles do."""
    package(
        "size-headings.docx",
        body(
            paragraph("Our procedures", style="Heading1"),
            paragraph("Fair and lawful processing", size=16),
            paragraph(
                "We process personal data fairly and lawfully, in line with individuals' rights.",
                style="NumberedBody",
            ),
            paragraph("Who is responsible for this policy?", bold=True),
            paragraph("The Clerk is responsible for this policy and its review."),
            paragraph("Data security", size=16),
            paragraph("We keep personal data secure against loss or misuse.", style="NumberedBody"),
            paragraph("Review", style="Heading1"),
            paragraph("The Council reviews this policy every two years."),
        ),
        styles=(
            '<w:style w:type="paragraph" w:customStyle="1" w:styleId="NumberedBody">'
            '<w:name w:val="Numbered Body"/><w:basedOn w:val="Normal"/>'
            '<w:pPr><w:outlineLvl w:val="2"/></w:pPr></w:style>'
        ),
    )


def arabic_patterns() -> None:
    """Numbers typed in the ways Arabic legal drafting writes them: "المادة (1)", ordinal
    words, Arabic-Indic digits and letters in abjad order."""
    package(
        "arabic-patterns.docx",
        body(
            paragraph("المادة (1) التعريفات", bold=True, rtl=True),
            paragraph("يقصد بالكلمات الآتية المعاني المبينة أمام كل منها.", rtl=True),
            paragraph("المادة (2) النطاق", bold=True, rtl=True),
            paragraph("أولاً: تسري هذه السياسة على جميع الموظفين.", rtl=True),
            paragraph("ثانياً: تسري على المتعاقدين.", rtl=True),
            paragraph("المادة (3) الالتزامات", bold=True, rtl=True),
            paragraph("١- يلتزم الموظف بحماية البيانات.", rtl=True),
            paragraph("٢- يلتزم بالإبلاغ عن أي خرق:", rtl=True),
            paragraph("أ- خلال يوم عمل واحد.", rtl=True),
            paragraph("ب- إلى مسؤول حماية البيانات.", rtl=True),
            paragraph("ج- كتابياً.", rtl=True),
        ),
    )


def mixed_languages() -> None:
    """English and Arabic in one document, each clause in its own language."""
    package(
        "mixed-languages.docx",
        body(
            paragraph("Purpose", style="Heading1"),
            paragraph("This policy sets out how Acme protects personal data."),
            paragraph("الغرض", style="Heading1", rtl=True),
            paragraph("تحدد هذه السياسة كيف تحمي الشركة البيانات الشخصية.", rtl=True),
        ),
    )


def numbering_formats() -> None:
    """Word's list formats and rules: letters, numerals, Arabic letters and digits, legal
    numbering, a list that starts again, a level that never restarts, and a definition that
    stands for a numbering style."""
    package(
        "numbering-formats.docx",
        body(
            paragraph("Formats", style="Heading1"),
            paragraph("first", numbered=(30, 0)),
            paragraph("letter", numbered=(30, 1)),
            paragraph("numeral", numbered=(30, 2)),
            paragraph("second", numbered=(30, 0)),
            paragraph("letter again", numbered=(30, 1)),
            paragraph("أبجد", numbered=(31, 0), rtl=True),
            paragraph("أبجد", numbered=(31, 0), rtl=True),
            paragraph("هندي", numbered=(32, 0), rtl=True),
            paragraph("legal", numbered=(33, 0)),
            paragraph("legal", numbered=(33, 1)),
            paragraph("restarted", numbered=(34, 0)),
            paragraph("never restarts", numbered=(35, 1)),
            paragraph("top", numbered=(35, 0)),
            paragraph("never restarts", numbered=(35, 1)),
            paragraph("linked", numbered=(36, 0)),
        ),
        numbering=(
            definition(30, [("decimal", "%1."), ("lowerLetter", "(%2)"), ("lowerRoman", "(%3)")])
            + definition(31, [("arabicAbjad", "%1-")])
            + definition(32, [("hindiNumbers", "%1.")])
            + definition(33, [("upperRoman", "%1."), ("lowerLetter", "%1.%2")], legal=1)
            + definition(35, [("decimal", "%1."), ("decimal", "(%2)")], restart_never=1)
            + definition(36, [], link="ListStyle")
            + instance(30, 30)
            + instance(31, 31)
            + instance(32, 32)
            + instance(33, 33)
            + instance(34, 30, {0: 5})
            + instance(35, 35)
            + instance(36, 36)
            + instance(37, 30)
        ),
        styles=(
            '<w:style w:type="numbering" w:customStyle="1" w:styleId="ListStyle">'
            '<w:name w:val="List Style"/><w:pPr><w:numPr><w:numId w:val="37"/></w:numPr></w:pPr>'
            "</w:style>"
        ),
    )


def main(folder: Path = HERE) -> None:
    global target
    target = folder
    heading_styles()
    automatic_numbering()
    numbered_headings()
    bold_headings()
    typed_numbers()
    arabic_sections()
    requirements_table()
    word_constructs()
    size_headings()
    arabic_patterns()
    mixed_languages()
    numbering_formats()


if __name__ == "__main__":
    main()
