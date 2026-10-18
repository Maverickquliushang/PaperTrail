"""Curated OpenAlex source IDs verified against /sources on 2026-10-18.

These are indexing routes, not an exhaustive or independent acceptance audit.
Do not include generic LNCS/PMLR series: they contain unrelated conferences.
"""

CONFERENCE_SOURCES = {
    "NeurIPS": ["S4363606243"],
    "ICML": ["S4306419644"],
    "ICLR": ["S4306419637"],
    "CVPR": ["S4210176548"],
    "ICCV": ["S7407086902", "S4363607764", "S4306419272"],
    "ECCV": ["S4306418318"],
    "ACL": ["S4363608652"],
    "EMNLP": ["S4363608991", "S4306418267"],
    "AAAI": ["S4210191458"],
    "IJCAI": ["S4306419999"],
    "KDD": ["S7407088418", "S4363608767", "S4306420424"],
}
OPENREVIEW_GROUPS = {"ICLR": "ICLR.cc", "ICML": "ICML.cc", "NeurIPS": "NeurIPS.cc"}
