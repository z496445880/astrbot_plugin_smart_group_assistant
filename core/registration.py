"""自动报名模块：基于 LLM 识别的报名方式，发送私聊、申请加群。"""

from __future__ import annotations

from astrbot.api import logger

from .utils import extract_qq_group_id


def _build_registration_message(owner_info: dict, activity_name: str, required_info: str = "") -> str:
    """根据主人的个人信息构建报名消息。

    Args:
        owner_info: 主人的个人信息字典
        activity_name: 活动名称
        required_info: 报名方要求提供的信息描述（如"姓名+学号"），用于优化消息格式

    Returns:
        格式化的报名消息。
    """
    name = owner_info.get("name", "")
    student_id = owner_info.get("student_id", "")
    id_card = owner_info.get("id_card", "")
    gender = owner_info.get("gender", "")
    college = owner_info.get("college", "")
    major = owner_info.get("major", "")
    class_name = owner_info.get("class_name", "")
    grade = owner_info.get("grade", "")

    lines = [
        f"你好！我对你发布的「{activity_name}」活动很感兴趣，以下是我的报名信息：",
        "",
    ]
    if name:
        lines.append(f"姓名：{name}")
    if gender:
        lines.append(f"性别：{gender}")
    if college:
        lines.append(f"学院：{college}")
    if major:
        lines.append(f"专业：{major}")
    if student_id:
        lines.append(f"学号：{student_id}")
    if grade:
        lines.append(f"年级：{grade}")
    if class_name:
        lines.append(f"班级：{class_name}")
    if id_card:
        lines.append(f"身份证号：{id_card}")
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

    try:
        client = event.bot

        # Napcat 扩展 API
        try:
            await client.api.call_action(
                "send_group_join_request_async",
                group_id=int(group_id),
                message=reason or "申请加入群聊",
            )
            logger.info(f"[智能群助手] 已向群 {group_id} 发送加群申请(Napcat)")
            return True
        except Exception:
            pass

        # 通用扩展 API
        try:
            await client.api.call_action(
                "send_group_join_request",
                group_id=int(group_id),
                message=reason or "我是对活动感兴趣的成员",
            )
            logger.info(f"[智能群助手] 已向群 {group_id} 发送加群申请")
            return True
        except Exception:
            pass

        logger.warning(f"[智能群助手] 所有加群方式均失败: {group_id}")
        return False

    except Exception as e:
        logger.error(f"[智能群助手] 申请加群 {group_id} 失败: {e}")
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

    # ── 1. 私聊报名 ──
    if method_type in ("private_message", "send_info"):
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
            fallback_qq = extract_qq_group_id(reg_analysis.get("method_detail", ""))
            if fallback_qq:
                success = await send_private_message_to_publisher(
                    event, fallback_qq, owner_info, activity_name, required_info
                )
                if success:
                    results.append(f"已私聊 {fallback_qq} 发送报名信息")
                else:
                    results.append(f"私聊 {fallback_qq} 发送报名信息失败")
            else:
                logger.info(f"[智能群助手] 报名方式要求私聊但未找到目标QQ")
                results.append(f"报名需私聊，但未找到目标QQ号，请手动处理（AI分析: {action_suggestion}）")

    # ── 2. 加群报名 ──
    elif method_type == "join_group":
        if target_group_id and target_group_id.isdigit():
            reason = f"我对「{activity_name}」活动感兴趣，申请加群"
            success = await join_qq_group(event, target_group_id, reason)
            if success:
                results.append(f"已申请加群 {target_group_id}")
            else:
                results.append(f"申请加群 {target_group_id} 失败（可能需手动加群）")
        else:
            # 尝试从原文提取群号
            extracted = extract_qq_group_id(reg_analysis.get("method_detail", ""))
            if extracted:
                reason = f"我对「{activity_name}」活动感兴趣，申请加群"
                success = await join_qq_group(event, extracted, reason)
                if success:
                    results.append(f"已申请加群 {extracted}")
                else:
                    results.append(f"申请加群 {extracted} 失败（可能需手动加群）")
            else:
                results.append(f"报名需加群，但未找到群号，请手动处理（AI分析: {action_suggestion}）")

    # ── 3. 其他报名方式 ──
    else:
        # 对于 scan_qr / fill_form / other，机器人无法自动操作
        detail = reg_analysis.get("method_detail", "")
        results.append(f"报名方式: {detail}（需手动操作）")
        if action_suggestion:
            results.append(f"AI建议: {action_suggestion}")

    if not results:
        results.append("未找到可执行的报名方式，请手动处理")

    return results
