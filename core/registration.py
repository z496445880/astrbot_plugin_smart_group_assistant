"""自动报名模块：发送私聊、申请加群。"""

from __future__ import annotations

from astrbot.api import logger

from .utils import extract_qq_group_id


def _build_registration_message(owner_info: dict, activity_name: str) -> str:
    """根据主人的个人信息构建报名消息。

    Args:
        owner_info: 主人的个人信息字典，包含 name/student_id/id_card/gender/class_name/grade
        activity_name: 活动名称

    Returns:
        格式化的报名消息。
    """
    name = owner_info.get("name", "")
    student_id = owner_info.get("student_id", "")
    id_card = owner_info.get("id_card", "")
    gender = owner_info.get("gender", "")
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
    if student_id:
        lines.append(f"学号：{student_id}")
    if grade:
        lines.append(f"年级：{grade}")
    if class_name:
        lines.append(f"班级：{class_name}")
    if id_card:
        lines.append(f"身份证号：{id_card}")
    lines.append("")
    lines.append("请问如何进一步完成报名？谢谢！")

    return "\n".join(lines)


async def send_private_message_to_publisher(
    event,
    organizer_qq: str,
    owner_info: dict,
    activity_name: str,
) -> bool:
    """向活动发布者发送包含个人信息的报名私聊消息。

    Args:
        event: AstrMessageEvent 对象
        organizer_qq: 发布者的QQ号
        owner_info: 主人的个人信息字典
        activity_name: 活动名称

    Returns:
        是否发送成功。
    """
    if not organizer_qq or not organizer_qq.isdigit():
        logger.warning(f"[智能群助手] 无效的发布者QQ号: {organizer_qq}")
        return False

    message = _build_registration_message(owner_info, activity_name)

    try:
        client = event.bot
        await client.api.call_action(
            "send_private_msg",
            user_id=int(organizer_qq),
            message=message,
        )
        logger.info(f"[智能群助手] 已向发布者 {organizer_qq} 发送报名私聊: {activity_name}")
        return True
    except Exception as e:
        logger.error(f"[智能群助手] 向发布者 {organizer_qq} 发送私聊失败: {e}")
        return False


async def join_qq_group(event, group_id: str, reason: str = "") -> bool:
    """尝试申请加入指定的QQ群。

    使用 OneBot V11 / Napcat 协议尝试加入群聊。

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
    config: dict,
) -> list[str]:
    """根据活动信息中的报名方式，自动执行报名操作。

    Args:
        event: AstrMessageEvent 对象
        activity_info: 活动信息字典（classifier.extract_activity_info 的输出）
        config: 插件配置

    Returns:
        操作结果描述列表，如 ["已私聊发布者123456", "已申请加群789012"]。
    """
    results = []
    activity_name = activity_info.get("activity_name", "未知活动")
    registration_method = activity_info.get("registration_method", "")
    organizer_qq = activity_info.get("organizer_qq", "")
    activity_group_id = activity_info.get("group_id", "")

    # 1. 私聊发布者
    owner_info = config.get("owner_info", {})

    if organizer_qq and organizer_qq.isdigit():
        success = await send_private_message_to_publisher(
            event, organizer_qq, owner_info, activity_name
        )
        if success:
            results.append(f"已私聊发布者 {organizer_qq}")
        else:
            results.append(f"私聊发布者 {organizer_qq} 失败")
    elif "私聊" in registration_method:
        logger.info(f"[智能群助手] 报名方式要求私聊但未提取到发布者QQ")

    # 2. 申请加群
    if activity_group_id and activity_group_id.isdigit():
        reason = f"我对「{activity_name}」活动感兴趣，申请加群"
        success = await join_qq_group(event, activity_group_id, reason)
        if success:
            results.append(f"已申请加群 {activity_group_id}")
        else:
            results.append(f"申请加群 {activity_group_id} 失败（可能需手动加群）")
    elif not activity_group_id:
        extracted_group = extract_qq_group_id(registration_method)
        if extracted_group:
            reason = f"我对「{activity_name}」活动感兴趣，申请加群"
            success = await join_qq_group(event, extracted_group, reason)
            if success:
                results.append(f"已申请加群 {extracted_group}")
            else:
                results.append(f"申请加群 {extracted_group} 失败（可能需手动加群）")

    if not results:
        results.append("未找到可执行的报名方式，请手动处理")

    return results
