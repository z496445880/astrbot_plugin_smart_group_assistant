"""自动报名模块：基于 LLM 识别的报名方式，发送私聊、申请加群。"""

from __future__ import annotations

from astrbot.api import logger

from .utils import extract_qq_group_id


def _build_registration_message(owner_info: dict, activity_name: str, required_info: str = "") -> str:
    """根据主人的个人信息和报名要求构建消息。

    只发送报名方实际要求的字段，不泄露多余隐私。
    如果报名方未明确要求，则默认只发送 姓名+学号+学院+专业+班级。

    Args:
        owner_info: 主人的个人信息字典
        activity_name: 活动名称
        required_info: 报名方要求提供的信息描述（如"姓名+学号"，LLM从原文提取）

    Returns:
        格式化的报名消息。
    """
    # 字段映射：required_info 中的中文 → owner_info 的 key
    FIELD_MAP = {
        "姓名": "name",
        "学号": "student_id",
        "性别": "gender",
        "学院": "college",
        "专业": "major",
        "班级": "class_name",
        "年级": "grade",
    }

    # 解析 required_info，确定需要哪些字段
    if required_info:
        needed_keys = set()
        for cn_name, key in FIELD_MAP.items():
            if cn_name in required_info:
                needed_keys.add(key)
        # 如果 LLM 成功识别了要求，只发送要求的字段
        if needed_keys:
            logger.info(f"[智能群助手] 报名要求字段: {needed_keys}")
            return _format_message(
                owner_info, activity_name, include_only=needed_keys
            )

    # 兜底：报名方未明确要求时，默认不发身份证号（保护隐私）
    logger.info("[智能群助手] 报名未明确要求字段，默认发送非敏感信息")
    default_keys = {"name", "student_id", "college", "major", "grade", "class_name", "gender"}
    return _format_message(owner_info, activity_name, include_only=default_keys)


def _format_message(
    owner_info: dict,
    activity_name: str,
    include_only: set,
) -> str:
    """按需格式化报名消息，只包含指定字段。"""
    FIELD_LABELS = [
        ("name", "姓名"),
        ("gender", "性别"),
        ("college", "学院"),
        ("major", "专业"),
        ("student_id", "学号"),
        ("grade", "年级"),
        ("class_name", "班级"),
    ]

    lines = [
        f"你好！我对你发布的「{activity_name}」活动很感兴趣，以下是我的报名信息：",
        "",
    ]

    for key, label in FIELD_LABELS:
        if key in include_only:
            value = owner_info.get(key, "")
            if value:
                lines.append(f"{label}：{value}")

    lines.append("")
    lines.append("期待参与！谢谢！")

    return "\n".join(lines)


async def send_private_message_to_publisher(
    event,
    target_qq: str,
    owner_info: dict,
    activity_name: str,
    required_info: str = "",
) -> bool:
    """向指定QQ号发送包含个人信息的报名私聊。

    Args:
        event: AstrMessageEvent 对象
        target_qq: 目标QQ号
        owner_info: 主人的个人信息字典
        activity_name: 活动名称
        required_info: 报名方要求提供的信息

    Returns:
        是否发送成功。
    """
    if not target_qq or not target_qq.isdigit():
        logger.warning(f"[智能群助手] 无效的目标QQ号: {target_qq}")
        return False

    message = _build_registration_message(owner_info, activity_name, required_info)

    try:
        client = event.bot
        await client.api.call_action(
            "send_private_msg",
            user_id=int(target_qq),
            message=message,
        )
        logger.info(f"[智能群助手] 已向 {target_qq} 发送报名私聊: {activity_name}")
        return True
    except Exception as e:
        logger.error(f"[智能群助手] 向 {target_qq} 发送私聊失败: {e}")
        return False


async def join_qq_group(event, group_id: str, reason: str = "") -> bool:
    """尝试申请加入指定的QQ群。

    QQ 机器人主动加群受平台限制，大部分协议端不支持。会尝试所有已知的 API。

    Args:
        event: AstrMessageEvent 对象
        group_id: 目标群号
        reason: 加群理由

    Returns:
        是否操作成功（不代表群管理员已同意）。
    """
    if not group_id or not group_id.isdigit():
        logger.warning(f"[智能群助手] 无效的群号: {group_id}")
        return False

    client = event.bot
    join_msg = reason or "申请加入群聊"

    # 依次尝试各种 Napcat / OneBot V11 扩展 API
    apis_to_try = [
        # Napcat 新版: set_group_join_request
        ("set_group_join_request", {"group_id": int(group_id), "message": join_msg, "action": "invite"}),
        # Napcat: 主动申请加群
        ("send_group_join_request", {"group_id": int(group_id), "message": join_msg}),
        # LLOneBot / Lagrange 可能支持的
        ("join_group", {"group_id": int(group_id), "message": join_msg}),
        # Napcat 旧版
        ("_send_group_join_request", {"group_id": int(group_id), "message": join_msg}),
    ]

    for api_name, params in apis_to_try:
        try:
            await client.api.call_action(api_name, **params)
            logger.info(f"[智能群助手] 加群成功 [{api_name}]: {group_id}")
            return True
        except Exception:
            continue

    logger.warning(f"[智能群助手] 所有加群 API 均失败: {group_id}（QQ机器人主动加群受平台限制，属正常现象）")
    return False


async def execute_registration(
    event,
    activity_info: dict,
    reg_analysis: dict,
    config: dict,
) -> list[str]:
    """根据 LLM 的报名方式分析结果，自动执行报名操作。

    Args:
        event: AstrMessageEvent 对象
        activity_info: 活动基本信息（classifier.extract_activity_info 的输出）
        reg_analysis: 报名方式分析结果（classifier.analyze_registration 的输出）
        config: 插件配置

    Returns:
        操作结果描述列表。
    """
    results = []
    activity_name = activity_info.get("activity_name", "未知活动")
    method_type = reg_analysis.get("method_type", "none")
    has_registration = reg_analysis.get("has_registration", False)

    if not has_registration:
        results.append("未检测到报名方式，请手动报名")
        return results

    # 确定目标QQ号：优先用LLM提取的 → 活动信息中的 → 消息发送者本人（发布者就是发消息的人）
    sender_qq = str(event.get_sender_id()) if hasattr(event, "get_sender_id") else ""
    target_qq = (
        reg_analysis.get("target_qq", "")
        or activity_info.get("organizer_qq", "")
        or sender_qq  # 兜底：群消息的发送者就是活动发布者
    )
    target_group_id = reg_analysis.get("target_group_id", "") or activity_info.get("group_id", "")
    required_info = reg_analysis.get("required_info", "")
    action_suggestion = reg_analysis.get("action_suggestion", "")

    owner_info = config.get("owner_info", {})

    # ── 1. 私聊报名（如果需要） ──
    needs_private_msg = method_type in ("private_message", "send_info")
    # 即使 method_type 不是 private_message，如果报名方式描述中包含"私聊/私信"也尝试
    method_detail = reg_analysis.get("method_detail", "")
    if not needs_private_msg and ("私聊" in method_detail or "私信" in method_detail):
        needs_private_msg = True

    if needs_private_msg:
        if target_qq and target_qq.isdigit():
            success = await send_private_message_to_publisher(
                event, target_qq, owner_info, activity_name, required_info
            )
            if success:
                results.append(f"已私聊 {target_qq} 发送报名信息")
            else:
                results.append(f"私聊 {target_qq} 发送报名信息失败")
        else:
            # 尝试从原文中找QQ号
            fallback_qq = extract_qq_group_id(method_detail)
            if fallback_qq:
                success = await send_private_message_to_publisher(
                    event, fallback_qq, owner_info, activity_name, required_info
                )
                if success:
                    results.append(f"已私聊 {fallback_qq} 发送报名信息")
                else:
                    results.append(f"私聊 {fallback_qq} 发送报名信息失败")
            else:
                logger.info(f"[智能群助手] 报名方式要求私聊但未找到目标QQ，使用发送者QQ兜底")
                if target_qq and target_qq.isdigit():
                    success = await send_private_message_to_publisher(
                        event, target_qq, owner_info, activity_name, required_info
                    )
                    if success:
                        results.append(f"已私聊 {target_qq} 发送报名信息")
                    else:
                        results.append(f"私聊 {target_qq} 失败")
                else:
                    results.append(f"报名需私聊但未找到目标QQ，请手动处理")

    # ── 2. 加群报名（独立判断，可以和私聊同时执行）──
    # 只要原文中有群号，无论 method_type 是什么，都尝试加群
    needs_join_group = method_type == "join_group" or bool(target_group_id)

    if needs_join_group:
        if target_group_id and target_group_id.isdigit():
            reason = f"我对「{activity_name}」活动感兴趣，申请加群"
            success = await join_qq_group(event, target_group_id, reason)
            if success:
                results.append(f"已申请加群 {target_group_id}")
            else:
                results.append(f"申请加群 {target_group_id} 失败（QQ机器人主动加群受平台限制，请手动搜索群号申请加入）")
        else:
            # 尝试从原文或报名方式描述中提取群号
            extracted = extract_qq_group_id(method_detail) or extract_qq_group_id(str(activity_info))
            if extracted:
                reason = f"我对「{activity_name}」活动感兴趣，申请加群"
                success = await join_qq_group(event, extracted, reason)
                if success:
                    results.append(f"已申请加群 {extracted}")
                else:
                    results.append(f"申请加群 {extracted} 失败（QQ机器人主动加群受平台限制，请手动搜索群号申请加入）")
            else:
                results.append(f"报名需加群但未找到群号，请手动处理")

    # ── 3. 其他报名方式（没有私聊也没有加群）──
    if not needs_private_msg and not needs_join_group:
        detail = method_detail
        results.append(f"报名方式: {detail}（需手动操作）")
        if action_suggestion:
            results.append(f"AI建议: {action_suggestion}")

    if not results:
        results.append("未找到可执行的报名方式，请手动处理")

    return results
