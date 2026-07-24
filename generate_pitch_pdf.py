"""
Generates Alt3red one-page leave-behind PDF.
Run: python generate_pitch_pdf.py
Output: Alt3red_Pitch.pdf
"""
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

W, H = letter

# ── Fonts ────────────────────────────────────────────────────────────────────
# Superclarendon (slab serif) for display — trade/craftsman voice, distinctive.
# Avenir Next (geometric sans) for body/labels — clean contrast pairing.
pdfmetrics.registerFont(TTFont("Clarendon-Bold", "fonts/Superclarendon-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Clarendon", "fonts/Superclarendon-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Avenir", "fonts/AvenirNext-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Avenir-Medium", "fonts/AvenirNext-Medium.ttf"))
pdfmetrics.registerFont(TTFont("Avenir-Demi", "fonts/AvenirNext-DemiBold.ttf"))
pdfmetrics.registerFont(TTFont("Avenir-Heavy", "fonts/AvenirNext-Heavy.ttf"))

# ── Palette — "Committed" strategy: one saturated brand color (rust/clay), ─────
# warm ink, near-neutral paper. Reference: hardware-store signage / workwear,
# not SaaS navy-indigo-gold-green.
INK     = colors.HexColor("#241E1A")   # warm near-black
RUST    = colors.HexColor("#B8452F")   # brand — burnt clay/rust
RUST_DK = colors.HexColor("#8F3320")   # rust shade, for text-on-paper accents
PAPER   = colors.HexColor("#FAF9F6")   # near-neutral off-white, minimal chroma
CREAM_LN= colors.HexColor("#E7E1D8")   # hairline / rule on paper
SAND    = colors.HexColor("#EDE6DA")   # tile bg (non-highlighted), warm neutral
MUTED   = colors.HexColor("#6B6058")   # secondary text, warm gray
WHITE   = colors.HexColor("#FAF9F6")

# ── Styles ───────────────────────────────────────────────────────────────────
def S(name, **kw):
    base = dict(fontName="Avenir", fontSize=9.5, leading=14.5,
                textColor=INK, spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(name, **base)

s_wordmark   = S("wordmark",  fontName="Clarendon-Bold", fontSize=34,
                 textColor=PAPER, alignment=TA_CENTER, leading=36,
                 tracking=0)
s_tag        = S("tag",       fontName="Avenir-Medium", fontSize=10.5,
                 textColor=colors.HexColor("#FBE9E2"), alignment=TA_CENTER,
                 leading=15)

s_pullquote  = S("pullquote", fontName="Clarendon", fontSize=19,
                 textColor=INK, leading=25, spaceBefore=2)
s_body       = S("body",      fontSize=10, leading=15.5, textColor=INK)
s_subhead    = S("subhead",   fontName="Clarendon-Bold", fontSize=14,
                 textColor=INK, spaceBefore=4, spaceAfter=6)

s_pkg_name_w = S("pkg_name_w", fontName="Avenir-Heavy", fontSize=12,
                 textColor=PAPER, alignment=TA_CENTER, leading=15)
s_pkg_name_k = S("pkg_name_k", fontName="Avenir-Heavy", fontSize=12,
                 textColor=RUST_DK, alignment=TA_CENTER, leading=15)
s_pkg_setup_w= S("pkg_setup_w",fontName="Avenir", fontSize=8, textColor=colors.HexColor("#FBE9E2"),
                 alignment=TA_CENTER)
s_pkg_setup_k= S("pkg_setup_k",fontName="Avenir", fontSize=8, textColor=MUTED,
                 alignment=TA_CENTER)
s_pkg_price_w= S("pkg_price_w",fontName="Clarendon-Bold", fontSize=21,
                 textColor=PAPER, alignment=TA_CENTER, leading=25)
s_pkg_price_k= S("pkg_price_k",fontName="Clarendon-Bold", fontSize=21,
                 textColor=INK, alignment=TA_CENTER, leading=25)
s_pkg_feat_w = S("pkg_feat_w", fontSize=8.3, leading=13, textColor=PAPER)
s_pkg_feat_k = S("pkg_feat_k", fontSize=8.3, leading=13, textColor=INK)

s_ch_label   = S("ch_label",  fontName="Avenir-Demi", fontSize=8, alignment=TA_CENTER,
                 leading=11, textColor=INK)
s_ch_label_r = S("ch_label_r",fontName="Avenir-Demi", fontSize=8, alignment=TA_CENTER,
                 leading=11, textColor=RUST_DK)
s_cell       = S("cell",      fontSize=8.3, alignment=TA_CENTER, textColor=MUTED)
s_cell_win   = S("cell_win",  fontName="Avenir-Demi", fontSize=8.3, alignment=TA_CENTER,
                 textColor=RUST_DK)
s_row_label  = S("row_label", fontSize=8.3, textColor=INK)

s_roi_lead   = S("roi_lead",  fontName="Clarendon", fontSize=13, textColor=PAPER,
                 alignment=TA_CENTER, leading=19)
s_roi_num    = S("roi_num",   fontName="Clarendon-Bold", fontSize=17, textColor=PAPER)
s_roi_label  = S("roi_label", fontName="Avenir", fontSize=8.3,
                 textColor=colors.HexColor("#FBE9E2"))

s_contact    = S("contact",   fontSize=8.3, textColor=MUTED, alignment=TA_CENTER)
s_fine       = S("fine",      fontSize=7.5, textColor=MUTED, alignment=TA_CENTER)


def build():
    doc = SimpleDocTemplate(
        "Alt3red_Pitch.pdf",
        pagesize=letter,
        leftMargin=0.55*inch,
        rightMargin=0.55*inch,
        topMargin=0,
        bottomMargin=0.22*inch,
    )
    CW = W - 1.1*inch
    story = []

    # ── HEADER BAND ─────────────────────────────────────────────────────────
    header = Table([[Paragraph("Alt3red", s_wordmark)],
                     [Paragraph("AI voice agents for local business, built and managed for you", s_tag)]],
                    colWidths=[CW])
    header.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), RUST),
        ("TOPPADDING",   (0,0), (0,0), 18),
        ("BOTTOMPADDING",(0,0), (0,0), 3),
        ("TOPPADDING",   (0,1), (0,1), 0),
        ("BOTTOMPADDING",(0,1), (0,1), 14),
    ]))
    story.append(header)
    story.append(Spacer(1, 7))

    # ── LEAD — pull-quote style, no eyebrow ────────────────────────────────
    story.append(Paragraph(
        "The phone rings. Nobody answers. The customer calls the next place.",
        s_pullquote
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "A barbershop missing three calls a day loses over <b>$27,000 a year</b> in walk-away "
        "revenue. Alt3red answers every call, day or night, books the appointment, and texts "
        "a confirmation, on the phone number you already have. Your customers won't "
        "notice anything changed except that someone always picks up.",
        s_body
    ))

    story.append(Spacer(1, 7))

    # ── PACKAGES ────────────────────────────────────────────────────────────
    story.append(Paragraph("Three ways to start", s_subhead))

    def pkg_cell(name, setup, mo, features, highlight=False):
        if highlight:
            return [
                Paragraph(name, s_pkg_name_w),
                Paragraph(f"${setup} setup", s_pkg_setup_w),
                Paragraph(f"${mo}<font size='9'>/mo</font>", s_pkg_price_w),
                Paragraph("<br/>".join(f"&#8226;&nbsp; {f}" for f in features), s_pkg_feat_w),
            ]
        return [
            Paragraph(name, s_pkg_name_k),
            Paragraph(f"${setup} setup", s_pkg_setup_k),
            Paragraph(f"${mo}<font size='9'>/mo</font>", s_pkg_price_k),
            Paragraph("<br/>".join(f"&#8226;&nbsp; {f}" for f in features), s_pkg_feat_k),
        ]

    c1 = pkg_cell("CORE", "1,000", "149", [
        "AI answers every call, 24/7",
        "FAQ handling: hours, pricing, location",
        "Appointment booking to your calendar",
        "SMS confirmation to every caller",
        "Call log, see every interaction",
        "Keep your existing phone number",
    ])
    c2 = pkg_cell("GROWTH", "1,200", "199", [
        "Everything in Core",
        "After-hours booking script",
        "Human handoff when caller escalates",
        "Owner dashboard: bookings + history",
        "Monthly performance report",
        "Number porting available (+$150)",
    ], highlight=True)
    c3 = pkg_cell("PRO", "1,500", "249", [
        "Everything in Growth",
        "Custom named voice persona",
        "Multi-staff calendar routing",
        "Priority support: 24hr response",
        "Quarterly check-in call",
        "Quarterly script & pricing update",
    ])

    COL = CW / 3
    pkg_table = Table([[c1, c2, c3]], colWidths=[COL, COL, COL])
    pkg_table.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (0,0), SAND),
        ("BACKGROUND",   (1,0), (1,0), RUST),
        ("BACKGROUND",   (2,0), (2,0), SAND),
        ("BOX",          (0,0), (0,0), 0.75, CREAM_LN),
        ("BOX",          (2,0), (2,0), 0.75, CREAM_LN),
        ("TOPPADDING",   (0,0), (-1,-1), 10),
        ("BOTTOMPADDING",(0,0), (-1,-1), 12),
        ("LEFTPADDING",  (0,0), (-1,-1), 11),
        ("RIGHTPADDING", (0,0), (-1,-1), 11),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    story.append(pkg_table)

    story.append(Spacer(1, 7))

    # ── COST COMPARISON ─────────────────────────────────────────────────────
    story.append(Paragraph("What this replaces", s_subhead))

    comp_data = [
        [
            "",
            Paragraph("Part-time<br/>receptionist", s_ch_label),
            Paragraph("Full-time<br/>receptionist", s_ch_label),
            Paragraph("Alt3red Growth", s_ch_label_r),
        ],
        [Paragraph("Monthly cost", s_row_label), Paragraph("$960&ndash;$1,200", s_cell), Paragraph("$2,400&ndash;$3,200", s_cell), Paragraph("$199", s_cell_win)],
        [Paragraph("Hours covered", s_row_label), Paragraph("20 hrs/week", s_cell), Paragraph("40 hrs/week", s_cell), Paragraph("24/7/365", s_cell_win)],
        [Paragraph("Sick days, no-shows", s_row_label), Paragraph("Yes", s_cell), Paragraph("Yes", s_cell), Paragraph("Never", s_cell_win)],
        [Paragraph("Handles simultaneous calls", s_row_label), Paragraph("No", s_cell), Paragraph("No", s_cell), Paragraph("Yes", s_cell_win)],
        [Paragraph("Books every caller", s_row_label), Paragraph("Inconsistent", s_cell), Paragraph("Yes", s_cell), Paragraph("Every time", s_cell_win)],
        [Paragraph("Annual cost", s_row_label), Paragraph("$11,500&ndash;$14,400", s_cell), Paragraph("$28,800&ndash;$38,400", s_cell), Paragraph("$3,588 + setup", s_cell_win)],
    ]
    col_w = CW / 4
    comp_table = Table(comp_data, colWidths=[col_w*1.35, col_w*0.95, col_w*0.95, col_w*0.75])
    comp_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), INK),
        ("TOPPADDING",    (0,0), (-1,0), 7),
        ("BOTTOMPADDING", (0,0), (-1,0), 7),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [PAPER, SAND]),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,1), (-1,-1), 4.5),
        ("BOTTOMPADDING", (0,1), (-1,-1), 4.5),
        ("LEFTPADDING",   (0,0), (0,-1), 8),
        ("LINEBELOW",     (0,0), (-1,0), 0.5, INK),
        ("LINEBELOW",     (0,1), (-1,-2), 0.4, CREAM_LN),
    ]))
    story.append(comp_table)

    story.append(Spacer(1, 7))

    # ── ROI — inline stat band, not repeated hero-metric tiles ─────────────
    roi_row = Table([[
        Paragraph("$770", s_roi_num), Paragraph("recovered<br/>per month", s_roi_label),
        Paragraph("11 hrs", s_roi_num), Paragraph("saved<br/>per week", s_roi_label),
        Paragraph("8:1", s_roi_num), Paragraph("return on<br/>Growth plan", s_roi_label),
        Paragraph("Day 1", s_roi_num), Paragraph("live,<br/>no training", s_roi_label),
    ]], colWidths=[0.85*inch, 0.95*inch, 0.85*inch, 0.85*inch, 0.65*inch, 0.95*inch, 0.85*inch, 0.95*inch])
    roi_row.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
    ]))

    roi_block = Table([
        [Paragraph("What it's worth, conservatively:", s_roi_lead)],
        [roi_row],
    ], colWidths=[CW])
    roi_block.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), INK),
        ("TOPPADDING",   (0,0), (0,0), 11),
        ("BOTTOMPADDING",(0,0), (0,0), 7),
        ("TOPPADDING",   (0,1), (0,1), 2),
        ("BOTTOMPADDING",(0,1), (0,1), 12),
        ("ALIGN",        (0,1), (0,1), "CENTER"),
    ]))
    story.append(roi_block)

    story.append(Spacer(1, 7))

    # ── FOOTER ───────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=CREAM_LN))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "Alt3red &middot; Greensboro, NC &middot; ajapaukese@gmail.com &middot; "
        "704-408-4648 &middot; linkedin.com/in/ajapaukese",
        s_contact
    ))
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        "Setup includes full configuration, calendar integration, call forwarding, "
        "and same-day go-live. Month-to-month. Cancel anytime.",
        s_fine
    ))

    doc.build(story)
    print("done: Alt3red_Pitch.pdf")


if __name__ == "__main__":
    build()
