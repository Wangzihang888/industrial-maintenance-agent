from app.state import AgentState

# ============================================================
# 4.1 Temperature Evaluation
# ============================================================

def evaluate_temperature(
    device_status: dict,
    temperature_records: list[dict],
) -> dict:
    """
    根据：

    1. 当前设备实时温度
    2. 最近历史温度记录
    3. 设备自身温度阈值

    判断设备综合温度风险。


    温度状态：

    normal:
        综合最高温度 < warning阈值


    warning:
        warning阈值
        <= 综合最高温度
        <= limit阈值


    critical:
        综合最高温度 > limit阈值



    注意：

    该函数只负责业务计算。

    不直接修改 AgentState。
    """


    # --------------------------------------------------------
    # 1. 获取设备温度阈值
    # --------------------------------------------------------

    temperature_warning = (
        device_status[
            "temperature_warning"
        ]
    )


    temperature_limit = (
        device_status[
            "temperature_limit"
        ]
    )



    # --------------------------------------------------------
    # 2. 当前实时温度
    # --------------------------------------------------------

    current_temperature = (
        device_status.get(
            "temperature"
        )
    )



    # --------------------------------------------------------
    # 3. 历史温度
    # --------------------------------------------------------

    historical_temperatures = [

        record["temperature"]

        for record

        in temperature_records

    ]



    # --------------------------------------------------------
    # 4. 合并当前 + 历史温度
    # --------------------------------------------------------

    all_temperatures = (
        historical_temperatures.copy()
    )


    if current_temperature is not None:

        all_temperatures.append(
            current_temperature
        )



    # --------------------------------------------------------
    # 5. 综合最高温度
    # --------------------------------------------------------

    max_temperature = (

        max(all_temperatures)

        if all_temperatures

        else None

    )



    # --------------------------------------------------------
    # 6. 无温度数据
    # --------------------------------------------------------

    if max_temperature is None:

        return {

            "temperature_warning":
                temperature_warning,


            "temperature_limit":
                temperature_limit,


            "max_temperature":
                None,


            "temperature_abnormal":
                False,


            "temperature_status":
                "unknown",

        }



    # --------------------------------------------------------
    # 7. 温度等级判断
    # --------------------------------------------------------

    if (
        max_temperature
        < temperature_warning
    ):

        temperature_status = (
            "normal"
        )


    elif (

        temperature_warning
        <= max_temperature
        <= temperature_limit

    ):

        temperature_status = (
            "warning"
        )


    else:

        temperature_status = (
            "critical"
        )



    # --------------------------------------------------------
    # 8. 是否严重异常
    # --------------------------------------------------------

    temperature_abnormal = (

        temperature_status
        == "critical"

    )



    return {

        "temperature_warning":
            temperature_warning,


        "temperature_limit":
            temperature_limit,


        "max_temperature":
            max_temperature,


        "temperature_abnormal":
            temperature_abnormal,


        "temperature_status":
            temperature_status,

    }


# ============================================================
# 5.4 Evaluate Temperature Node
# ============================================================


def evaluate_temperature_node(
    state: AgentState,
) -> dict:
    """
    人工查询：
        计算当前温度与历史温度的综合风险。

    自动监控任务：
        不重新判断风险。
        直接使用 Monitoring Engine 给出的
        trigger_risk_level 作为后续处置依据。
    """

    if state.get("execution_mode") == "automatic":
        return {}

    device_status = state.get("device_status")

    temperature_records = state.get(
        "temperature_records",
        [],
    )

    if not device_status:
        return {}

    result = evaluate_temperature(
        device_status=device_status,
        temperature_records=temperature_records,
    )

    return {
        "temperature_warning": result["temperature_warning"],
        "temperature_limit": result["temperature_limit"],
        "max_temperature": result["max_temperature"],
        "temperature_abnormal": result["temperature_abnormal"],
        "temperature_status": result["temperature_status"],
    }


# ============================================================
# 4.2 Action Decision
# ============================================================



def decide_action(
    risk_level: str,
) -> dict:
    """
    根据监控系统确定的处置类别，
    决定是否通知和申请维修工单。

    fault:
        E-101 / E-102 非温度故障

    warning / critical:
        温度异常等级
    """

    if risk_level == "normal":
        return {
            "need_notification": False,
            "need_ticket": False,
            "notification_level": None,
        }

    if risk_level == "warning":
        return {
            "need_notification": True,
            "need_ticket": False,
            "notification_level": "warning",
        }

    if risk_level == "critical":
        return {
            "need_notification": True,
            "need_ticket": True,
            "notification_level": "critical",
        }

    if risk_level == "fault":
        return {
            "need_notification": True,
            "need_ticket": True,
            "notification_level": "fault",
        }

    raise ValueError(
        f"不支持的处置类别：{risk_level}"
    )


# ============================================================
# 5.5 Decide Action Node
# ============================================================



def decide_action_node(
    state: AgentState,
) -> dict:
    """
    自动任务：
        使用 Monitoring Engine 给出的处置类别。

    非自动任务：
        保留原有温度分析决策。
    """

    if state.get("execution_mode") == "automatic":
        risk_level = state.get("trigger_risk_level")

        if risk_level not in (
            "warning",
            "critical",
            "fault",
        ):
            raise ValueError(
                "自动任务缺少有效 trigger_risk_level"
            )

    else:
        risk_level = state.get("temperature_status")

    if risk_level is None:
        return {}

    result = decide_action(
        risk_level=risk_level
    )

    return result
