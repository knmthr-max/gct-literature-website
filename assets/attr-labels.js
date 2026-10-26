// 論文の属性(部位・組織型・性別・年齢区分・治療・臨床テーマなど)の絞り込み項目と表示名。
// データ側の値(英語の選択肢)は scripts/sync_site_attributes.py が papers の "attrs" に入れる。
// 項目を足す・直すときは、そちらと合わせる。
export const FACETS = [
  { key: "th", id: "theme", ja: "臨床テーマ", en: "Clinical theme", open: true, values: {
    surgery: ["手術", "Surgery"], chemotherapy: ["化学療法", "Chemotherapy"], radiotherapy: ["放射線治療", "Radiotherapy"],
    surveillance: ["経過観察", "Surveillance"], late_effects: ["晩期合併症", "Late effects"], fertility: ["妊孕性", "Fertility"],
    diagnosis_imaging: ["画像・検査", "Imaging / tests"], epidemiology: ["疫学", "Epidemiology"],
    pathology_molecular: ["病理・分子", "Pathology / molecular"], prognosis: ["予後", "Prognosis"], qol: ["QOL", "QOL"] } },
  { key: "si", id: "site", ja: "原発部位", en: "Primary site", open: true, values: {
    testis: ["精巣", "Testis"], ovary: ["卵巣", "Ovary"], mediastinum: ["縦隔", "Mediastinum"],
    retroperitoneum: ["後腹膜", "Retroperitoneum"], sacrococcygeal: ["仙尾部", "Sacrococcygeal"],
    other_extragonadal: ["その他の性腺外", "Other extragonadal"], cns: ["中枢神経", "CNS"], multiple: ["複数部位", "Multiple sites"] } },
  { key: "hi", id: "histology", ja: "組織型", en: "Histology", values: {
    seminoma_germinoma: ["セミノーマ・ジャーミノーマ", "Seminoma / germinoma"], nonseminomatous_gct: ["非セミノーマ", "Non-seminomatous GCT"],
    mature_teratoma: ["成熟奇形腫", "Mature teratoma"], immature_teratoma: ["未熟奇形腫", "Immature teratoma"],
    teratoma_with_malignant_transformation: ["悪性転化を伴う奇形腫", "Teratoma with malignant transformation"],
    yolk_sac_tumor: ["卵黄嚢腫瘍", "Yolk sac tumor"], embryonal_carcinoma: ["胎児性癌", "Embryonal carcinoma"],
    choriocarcinoma: ["絨毛癌", "Choriocarcinoma"], gestational_choriocarcinoma: ["妊娠性絨毛癌", "Gestational choriocarcinoma"],
    mixed_gct: ["混合型", "Mixed GCT"], spermatocytic_tumor: ["精母細胞性腫瘍", "Spermatocytic tumor"],
    gonadoblastoma: ["性腺芽腫", "Gonadoblastoma"], gct_nos: ["胚細胞腫瘍(詳細不明)", "GCT, NOS"] } },
  { key: "sx", id: "sex", ja: "性別", en: "Sex", values: {
    male: ["男性", "Male"], female: ["女性", "Female"], mixed: ["男女", "Both"] } },
  { key: "ag", id: "age", ja: "年齢区分", en: "Age group", values: {
    infant: ["乳幼児(2歳未満)", "Infant (<2 y)"], child: ["小児(2〜12歳)", "Child (2-12 y)"], adolescent: ["思春期(13〜17歳)", "Adolescent (13-17 y)"],
    adult: ["成人(18〜64歳)", "Adult (18-64 y)"], elderly: ["高齢者(65歳以上)", "Elderly (65+ y)"], mixed: ["複数の年齢層", "Mixed ages"] } },
  { key: "tr", id: "treat", ja: "治療", en: "Treatment", values: {
    surgery: ["手術", "Surgery"], chemotherapy: ["化学療法", "Chemotherapy"], radiotherapy: ["放射線治療", "Radiotherapy"],
    observation: ["経過観察", "Observation"], high_dose_chemo_transplant: ["大量化学療法+移植", "High-dose chemo + transplant"] } },
];

// 研究デザインを選んだときだけ出す、そのデザイン固有の項目
const TRIAL = [
  { key: "ln", id: "line", ja: "治療ライン", en: "Line of therapy", values: {
    first_line: ["初回治療", "First line"], salvage: ["救済治療", "Salvage"], adjuvant: ["術後補助", "Adjuvant"],
    neoadjuvant: ["術前", "Neoadjuvant"], maintenance: ["維持", "Maintenance"], mixed: ["複数", "Mixed"] } },
  { key: "ep", id: "endpoint", ja: "主要評価項目", en: "Primary endpoint", values: {
    OS: ["全生存", "OS"], PFS: ["無増悪生存", "PFS"], response_rate: ["奏効率", "Response rate"], safety: ["安全性", "Safety"] } },
  { key: "ph", id: "phase", ja: "相", en: "Phase", values: {
    I: ["I", "I"], "I/II": ["I/II", "I/II"], II: ["II", "II"], "II/III": ["II/III", "II/III"], III: ["III", "III"] } },
];
export const SPECIFIC = {
  "RCT": { name: "trial", facets: TRIAL },
  "非ランダム化試験": { name: "trial", facets: TRIAL },
  "SR・MA": { name: "review", facets: [
    { key: "sc", id: "scope", ja: "統合の対象", en: "Scope", values: {
      treatment: ["治療", "Treatment"], diagnosis: ["診断", "Diagnosis"], prognosis: ["予後", "Prognosis"], epidemiology: ["疫学", "Epidemiology"] } },
    { key: "mt", id: "meta", ja: "定量的統合", en: "Quantitative synthesis", values: {
      yes: ["メタ解析あり", "Meta-analysis"], no: ["記述的のみ", "Narrative only"] } },
  ] },
  "観察研究": { name: "observational", facets: [
    { key: "st", id: "stype", ja: "研究の型", en: "Study type", values: {
      retrospective_cohort: ["後ろ向きコホート", "Retrospective cohort"], prospective_cohort: ["前向きコホート", "Prospective cohort"],
      case_control: ["症例対照", "Case-control"], cross_sectional: ["横断研究", "Cross-sectional"],
      registry_epidemiology: ["レジストリ・疫学", "Registry / epidemiology"], diagnostic_accuracy: ["診断精度", "Diagnostic accuracy"],
      prognostic_biomarker: ["予後・バイオマーカー", "Prognostic biomarker"], genetic_association: ["遺伝子関連", "Genetic association"],
      survey: ["調査", "Survey"] } },
  ] },
};

export const STAGE_LABEL = { I: ["I期", "Stage I"], II: ["II期", "Stage II"], III: ["III期", "Stage III"], IV: ["IV期", "Stage IV"] };
export const IGCCCG_LABEL = { good: ["IGCCCG 良好", "IGCCCG good"], intermediate: ["IGCCCG 中間", "IGCCCG intermediate"], poor: ["IGCCCG 不良", "IGCCCG poor"] };

// 選んだ研究デザインすべてに共通の固有項目(同じ種類のデザインだけを選んだとき)。無ければ []
export function specificFacets(designs) {
  const names = new Set([...designs].map((d) => SPECIFIC[d]?.name ?? ""));
  if (names.size !== 1) return [];
  const first = SPECIFIC[[...designs][0]];
  return first ? first.facets : [];
}
