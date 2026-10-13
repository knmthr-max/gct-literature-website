"""文献の「研究デザイン」分類(公開サイトのタグ)の定義。1論文に1つ。

2026-10-12 に、従来の固定7分類(症例報告/臨床研究/基礎研究/総説/ガイドライン/論説/レター)から次の9分類に変えた
(docs/decisions/2026-10-12_study_design_taxonomy.md)。画面では「基礎」と「臨床」の2つの大分類に分けて選べるようにする
(基礎・トランスレーショナル以外はすべて臨床)。

  決め方: 1) PubMed の出版タイプで確実に決まるもの(SR・MA、ガイドライン、RCT、非ランダム化試験、観察研究、その他)はそれを使う
          2) それ以外(出版タイプが症例報告・総説のもの、出版タイプで決まらない原著論文)は AI が題名・抄録から決める
"""

SR_MA = "SR・MA"
GUIDELINE = "ガイドライン・コンセンサス"
RCT = "RCT"
NON_RCT = "非ランダム化試験"
CASE = "症例報告・集積"
REVIEW = "総説"
OBSERVATIONAL = "観察研究"
BASIC = "基礎・トランスレーショナル"
OTHER = "その他"

CATEGORIES = (SR_MA, GUIDELINE, RCT, NON_RCT, CASE, REVIEW, OBSERVATIONAL, BASIC, OTHER)
# 大分類: 基礎・トランスレーショナル以外は臨床
GROUPS = {"clinical": tuple(c for c in CATEGORIES if c != BASIC), "basic": (BASIC,)}

# 出版タイプで決める分類(上から順に判定)。症例報告と総説の両方が付く論文は症例報告にする(2026-10-12)
PUBTYPE_RULES = (
    (SR_MA, {"Meta-Analysis", "Systematic Review", "Scoping Review"}),
    (GUIDELINE, {"Practice Guideline", "Guideline", "Consensus Development Conference"}),
    (RCT, {"Randomized Controlled Trial"}),
    (NON_RCT, {"Clinical Trial", "Clinical Trial, Phase I", "Clinical Trial, Phase II", "Clinical Trial, Phase III",
               "Clinical Trial, Phase IV", "Controlled Clinical Trial", "Pragmatic Clinical Trial", "Equivalence Trial"}),
    (CASE, {"Case Reports"}),
    (REVIEW, {"Review"}),
    (OBSERVATIONAL, {"Observational Study"}),
    (OTHER, {"Editorial", "Letter", "Comment", "Video-Audio Media", "Book Chapter", "Historical Article", "Biography",
             "Portrait", "Congress", "Clinical Conference", "Published Erratum", "Retraction Notice", "News", "Interview",
             "Lecture", "Newspaper Article", "Study Guide", "Duplicate Publication", "Retracted Publication",
             "Corrected and Republished Article"}),
)
# 出版タイプをそのまま信用する分類。症例報告・総説は、実は大きな後ろ向き研究だった等の誤りがあるので AI が見直す
TRUSTED = {SR_MA, GUIDELINE, RCT, NON_RCT, OBSERVATIONAL, OTHER}


def design_from_pubtypes(publication_types):
    """PubMed の出版タイプから分類を決める。決まらなければ None。"""
    types = set(publication_types or [])
    for category, matching in PUBTYPE_RULES:
        if types & matching:
            return category
    return None


def final_design(pubtype_design, ai_design):
    """出版タイプの分類と AI の分類から、最終の分類を決める。出版タイプで確実に決まるものを優先し、
    それ以外は AI の分類(分類として正しいときだけ)、AI の結果が無ければ出版タイプの分類。"""
    if pubtype_design in TRUSTED:
        return pubtype_design
    if ai_design in CATEGORIES:
        return ai_design
    return pubtype_design


def group_of(category):
    return "basic" if category == BASIC else "clinical"


# AI への指示(判定プロンプトと、分類だけの再判定の両方に使う)
DESIGN_NOTE = (
    "study_design: choose exactly ONE category for the paper's main design. "
    "SR・MA = systematic review and/or meta-analysis/pooled analysis of studies with an explicit search or quantitative "
    "pooling. "
    "ガイドライン・コンセンサス = clinical practice guideline, consensus statement or panel recommendation. "
    "RCT = randomized controlled trial (including secondary analyses of one). "
    "非ランダム化試験 = prospective clinical trial without randomization (single-arm phase I/II, non-randomized "
    "comparative trial). "
    "症例報告・集積 = descriptive report of individual patients: a single case report, or a descriptive case series "
    "that presents the clinical course/findings of the patients (however many), without a formal hypothesis, "
    "comparison groups or statistical analysis; a case report that also reviews the literature stays here. "
    "観察研究 = analytic study of patients or a population without an intervention assigned by the investigators, "
    "with a formal question and quantitative analysis (rates, comparisons between groups, survival or risk "
    "analysis, associations): retrospective or prospective cohort, case-control, cross-sectional, "
    "registry/epidemiology, diagnostic accuracy, prognostic/biomarker study, treatment-outcome analysis, human "
    "genetic association study, survey. "
    "総説 = narrative/overview/pictorial/historical review or state-of-the-art article without a systematic method. "
    "基礎・トランスレーショナル = laboratory research whose aim is mechanism or biology: cell lines, animals, "
    "molecular/genomic/epigenetic analyses, biospecimen biology, model development. "
    "その他 = editorial, letter/comment, news, book chapter, historical note/biography, conference item, erratum, "
    "video, or anything that fits none of the above. "
    "Judge by the design, not the topic. If the text is too short, use the title and the PubMed publication types."
)

DESIGN_ENUM = list(CATEGORIES)
