import pytest

from backend.feishu_workspace import search_request
from backend.models import SOURCES
from backend.query_language import english_keywords, search_body


@pytest.mark.parametrize("text,expected", [
    ("检索大模型低秩分解", "large language model low rank decomposition"),
    ("检索 大模型低秩分解", "large language model low rank decomposition"),
    ("请帮我找大模型量化的论文", "large language model quantization"),
    ("搜索大语言模型结构化剪枝", "large language model structured pruning"),
    ("查一下大模型知识蒸馏", "large language model knowledge distillation"),
    ("帮我搜关于大模型的低秩分解相关论文", "large language model low rank decomposition"),
    ("给我找多模态大模型训练后量化的研究", "multimodal large language model post training quantization"),
    ("查找 LLM 的量化和剪枝", "LLM quantization pruning"),
    ("大模型混合精度量化", "large language model mixed precision quantization"),
    ("检索增强生成", "retrieval augmented generation"),
    ("搜索图神经网络的知识蒸馏", "graph neural network knowledge distillation"),
    ("查一下计算机视觉目标检测", "computer vision object detection"),
    ("检索 low rank decomposition", "low rank decomposition"),
])
def test_research_topics_and_phrasings(text, expected):
    request = search_request(text)
    assert request.query == expected
    assert request.sources == list(SOURCES)
    assert request.sort == "date"


def test_existing_source_and_filter_syntax_remains_available():
    request = search_request("检索 arxiv,openreview 大模型低秩分解 | 最近=30 | 数量=20 | 排序=相关性 | 会议=ICLR")
    assert request.query == "large language model low rank decomposition"
    assert request.sources == ["arxiv", "openreview"]
    assert request.limit == 20 and request.sort == "relevance"
    assert request.conferences == ["ICLR"] and request.start_date and request.end_date
    assert search_request('检索 all "large language model" compression').query == '"large language model" compression'
    with pytest.raises(ValueError, match="来源无效"):
        search_request("检索 arxiv,unknown quantization")


@pytest.mark.parametrize("query", ["大模型不要量化", "大模型算命", "量化或剪枝", "大模型最近三年的量化"])
def test_unrecognized_qualifiers_are_not_silently_discarded(query):
    with pytest.raises(ValueError, match="没有发起检索"):
        english_keywords(query)


@pytest.mark.parametrize("command", ["设置 arxiv | 主题=大模型量化", "帮助 检索", "取消检索", "推荐 arxiv", "生成推荐 arxiv"])
def test_search_does_not_capture_management_commands(command):
    assert search_body(command) is None


@pytest.mark.parametrize("text", ["检索", "搜索", "帮我找", "检索 all", "检索论文"])
def test_missing_topic_never_creates_empty_search(text):
    with pytest.raises(ValueError):
        search_request(text)
