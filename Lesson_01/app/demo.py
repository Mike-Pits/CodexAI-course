"""Deterministic examples for UI testing, not a model or crisis classifier."""
import re


def demo_reply(message: str, business: dict) -> str:
    text = message.casefold().replace('ё', 'е')
    if any(word in text for word in ('суицид', 'самоуб', 'убить себя', 'покончить с собой', 'причинить себе вред', 'передозиров', 'опасност', 'навредить себе')):
        answer = ('Мне жаль, что вам сейчас так тяжело. Если есть непосредственная опасность, '
                  'немедленно обратитесь в местную экстренную службу и попросите человека рядом помочь. '
                  'Этот учебный чат не оказывает экстренную помощь и не может вызвать её за вас.')
    elif any(word in text for word in ('диагноз', 'лекарств', 'лечени', 'таблетк')):
        answer = ('Я администратор учебного сервиса, а не врач. Не могу ставить диагнозы или назначать лечение. '
                  'Для оценки состояния и выбора помощи обратитесь к квалифицированному специалисту.')
    elif any(word in text for word in ('доставк', 'скидк', 'промокод', 'игнорируй', 'игнорировать')):
        answer = 'У меня нет сведений об этом. Я могу показать только услуги, цены и расписание из учебной базы знаний.'
    elif any(word in text for word in ('запис', 'обратит', 'контакт', 'почт', 'телефон', 'адрес')):
        answer = business['booking'] + '\nКонтакт: ' + business['contact'] + '.'
    elif any(word in text for word in ('работает', 'работы', 'открыт', 'расписан', 'время', 'час', 'выходн')):
        answer = business['hours']
    elif any(word in text for word in ('цен', 'стоим', 'стоит', 'сколько', 'услуг', 'формат', 'консультац', 'знакомств')):
        services = business['services']
        if 'индивидуаль' in text:
            services = [services[1]]
        elif 'пар' in text or 'семейн' in text:
            services = [services[3]]
        elif 'утрат' in text or 'перемен' in text:
            services = [services[2]]
        elif 'знакомств' in text:
            services = [services[0]]
        answer = '\n'.join(f"{s['name']} — {s['duration_minutes']} мин., " +
                           ('бесплатно.' if s['price_rub'] == 0 else f"{s['price_rub']} ₽.") for s in services)
        answer += '\n' + business['format'] + '. Это демонстрационные услуги.'
    elif re.fullmatch(r'(привет|здравствуйте|добрый день|спасибо)[!.\s]*', text):
        answer = 'Здравствуйте! Можно спросить о стоимости консультаций, форматах, расписании и порядке обращения.'
    else:
        answer = ('Для этого вопроса нет подготовленного тестового ответа. Попробуйте: '
                  '«Сколько стоит индивидуальная консультация?», «Когда вы работаете?» или «Как записаться?»')
    return 'Тестовый ответ (без OpenAI)\n\n' + answer
