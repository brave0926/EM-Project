"""Patterns that user-facing medical text must not contain: doses, diagnoses, brand names and
prescription-only drugs (EN/RU/ZH/KO). Pure: no I/O. Used to validate LLM rewrites, the first-aid
knowledge base and the evaluation scenarios.

Generic product TYPES ("sterile dressing", "pain reliever suitable for you") are fine; named drugs
and amounts are not.
"""

from __future__ import annotations

import re

# A number followed by a drug amount unit (EN/RU/ZH/KO).
DOSE = re.compile(
    r"\d\s*(mg|mcg|µg|ml|iu|g\b|мг|мл|毫克|毫升|克|밀리그램|밀리리터|그램)"
    r"|\d\s*(tablets?|pills?|capsules?|таблет|капсул|片|粒|丸|알|정\b|캡슐)",
    re.IGNORECASE,
)
# Diagnoses ("you probably have ...", "диагноз", "诊断", "진단").
DIAGNOSIS = re.compile(
    r"diagnos|\byou (?:most )?(?:likely |probably |may )?(?:have|suffer from|are having) (?:a|an)\b"
    r"|\byou probably have\b"
    r"|\b(?:it|this) (?:is|looks like) (?:most )?(?:likely|probably) (?:a|an)\b"
    r"|диагноз|у вас,? (?:вероятно|скорее всего|похоже)|(?:это|похоже,?) (?:похоже на|скорее всего)"
    r"|诊断|你(?:可能|应该)?(?:患有|得了)|(?:很)?可能是.{0,6}(?:病|症|骨折|中风|心脏病)"
    r"|진단|(?:인|일) 것 같습니다|(?:으로|로) 보입니다|가능성이 높습니다",
    re.IGNORECASE,
)
# Brand names (small blocklist) and drug names: the knowledge base names product types only.
BRANDS = re.compile(
    r"tylenol|panadol|advil|nurofen|motrin|neosporin|bepanthen|savlon|germolene|band-aid|epipen|strepsils|vicks"
    r"|тайленол|панадол|нурофен|бепантен|стрепсилс"
    r"|泰诺|必理通|芬必得|美林|邦迪|息斯敏"
    r"|타이레놀|애드빌|부루펜|게보린|후시딘|마데카솔|대일밴드",
    re.IGNORECASE,
)
DRUG_NAMES = re.compile(
    r"paracetamol|acetaminophen|ibuprofen|aspirin|naproxen"
    r"|парацетамол|ибупрофен|аспирин"
    r"|对乙酰氨基酚|對乙醯胺基酚|布洛芬|阿司匹林"
    r"|아세트아미노펜|이부프로펜|아스피린",
    re.IGNORECASE,
)
PRESCRIPTION = re.compile(
    r"antibiotic|adrenaline|epinephrine|antivenom|codeine|morphine|opioid|steroid|prednis"
    r"|антибиот|адреналин|эпинефрин|кодеин|морфин|стероид"
    r"|抗生素|肾上腺素|腎上腺素|可待因|吗啡|激素"
    r"|항생제|아드레날린|에피네프린|코데인|모르핀|스테로이드",
    re.IGNORECASE,
)


def problems(text: str) -> list[str]:
    """Names of the rules the text breaks: dose, diagnosis, brand, drug_name, prescription."""
    checks = {"dose": DOSE, "diagnosis": DIAGNOSIS, "brand": BRANDS, "drug_name": DRUG_NAMES,
              "prescription": PRESCRIPTION}
    return [name for name, pattern in checks.items() if pattern.search(text)]
