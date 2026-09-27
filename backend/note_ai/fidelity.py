"""Conservative relation guards; these detect known errors, not all semantic changes."""
import re

SYNONYMS = {'不应将':'不要把', '不应把':'不要把', '不要将':'不要把', '尚未':'未', '还没有':'未', '还没':'未', '没有':'未', '暂时不':'暂不', '先不要改':'先别改', '暂时不要改':'先别改'}


def canonical(text):
    for old,new in SYNONYMS.items():
        text=text.replace(old,new)
    return text


def quantities(text):
    """Bind unit-bearing values to the closest explicit reference in each sentence.

    Preserve attribute words when explicitly present next to the value. Rejecting
    an ambiguous rewrite is preferable to treating an identifier set as proof.
    """
    pairs=set()
    for sentence in re.split(r'[。！？\n]',text):
        refs=list(re.finditer(r'\b[A-Z]{1,4}\d+\b',sentence))
        for match in re.finditer(r'(?<![A-Za-z_\d])\d+(?:\.\d+)?\s*(?:kOhm|ohm|MHz|kHz|Hz|mV|uV|V|mA|uA|A|uF|nF|pF|mm|mil|ms|ns|us|W|dB)(?![A-Za-z])',sentence):
            before=[r for r in refs if r.end()<=match.start()]
            subject=before[-1].group() if before else ''
            pairs.add((subject,re.sub(r'\s+','',match.group())))
    return pairs


def action_states(text):
    pairs=set()
    for clause in re.split(r'[。！？；，\n]',canonical(text)):
        refs=re.findall(r'\b[A-Z]{1,4}\d+\b',clause)
        for action in re.finditer(r'复测|测试|测量|上电|焊接|换料|修改|核对|确认|执行|完成|打开|保存|导出|整理|列出',clause):
            before=clause[max(0,action.start()-12):action.start()]
            # "记录修改前后的值" names the values to record; it does not say
            # that a modification has been performed or scheduled.
            if action.group()=='修改' and clause[action.end():].startswith('前后') and re.search(r'记(?:录)?',before):
                continue
            state='pending' if re.search(r'未|没|不|待|别',before) else 'planned' if re.search(r'准备|计划|打算|需要|应|再|要|等',before) else 'done' if re.search(r'已经|已|完成了',before) else None
            if state:
                pairs.add((tuple(refs),action.group(),state))
    return pairs


def check_relations(original,text):
    if quantities(original)!=quantities(text):
        raise ValueError('对象与数值单位的对应关系改变或变得不明确')
    # Subject-free action signatures still catch "未测量" -> "已测量".
    old={(a,s) for _,a,s in action_states(original)}
    new={(a,s) for _,a,s in action_states(text)}
    if old!=new:
        raise ValueError('操作与执行状态改变或遗漏')
    # Explicit subjects cannot exchange completed/pending states merely because
    # the bag of verbs and states happens to be the same.
    bound_old={(refs,a,s) for refs,a,s in action_states(original) if refs}
    bound_new={(refs,a,s) for refs,a,s in action_states(text) if refs}
    if bound_old!=bound_new:
        raise ValueError('对象与操作状态的对应关系改变或变得不明确')
