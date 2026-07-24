"""Health agent: safety template for medical questions."""

from .state import AgentState


_HEALTH_TEMPLATE = (
    "这属于健康/校内医疗服务问题，我不能替你做诊断，也不能建议具体用药。\n"
    "如果只是轻微不适，建议休息、观察体温和症状变化；如果出现高热不退、呼吸困难、胸痛、意识异常、严重过敏等情况，请马上寻求线下医疗帮助。\n"
    "我会优先检索校医、门诊、医保、公费医疗等校内医疗服务资料。请补充：你在哪个校区？是否发烧？是否需要校医室地址、开放时间或报销流程？"
)


def health_answer(state: AgentState) -> dict:
    """Set a health safety disclaimer and append clinical search terms."""
    state.answer = _HEALTH_TEMPLATE
    state.expanded_question = f"{state.expanded_question} 暨南大学 校医 门诊 医务室 医保 公费医疗"
    return {"status": "success", "detail": "使用医疗安全模板并补充校内服务检索词"}
