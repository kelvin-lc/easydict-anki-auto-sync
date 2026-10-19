"""Keep native Again/Good ratings for Easydict notes on Anki desktop."""
from aqt import gui_hooks

MODEL = 'Easydict English-Chinese'


def is_easydict(card):
    return card is not None and card.note().note_type()['name'] == MODEL


def answer_buttons(buttons, reviewer, card):
    if not is_easydict(card):
        return buttons
    return tuple(button for button in buttons if button[0] in (1, 3))


def allow_answer(answer, reviewer, card):
    proceed, ease = answer
    if is_easydict(card) and ease not in (1, 3):
        return False, ease
    return proceed, ease


gui_hooks.reviewer_will_init_answer_buttons.append(answer_buttons)
gui_hooks.reviewer_will_answer_card.append(allow_answer)
