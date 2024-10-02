GENRE_CHRISTIAN = 'christian'
GENRE_POP_DANCE = 'pop and dance'
GENRE_SOFT_ROCK = 'soft rock'
GENRE_HARD_ROCK = 'hard rock'
GENRE_METAL = 'metal'

LIST_GENRES = [
    GENRE_CHRISTIAN,
    GENRE_POP_DANCE,
    GENRE_SOFT_ROCK,
    GENRE_HARD_ROCK,
    GENRE_METAL,
]

GENRE_CHOICES = [
    [GENRE_CHRISTIAN, GENRE_CHRISTIAN],
    [GENRE_POP_DANCE, GENRE_POP_DANCE],
    [GENRE_SOFT_ROCK, GENRE_SOFT_ROCK],
    [GENRE_HARD_ROCK, GENRE_HARD_ROCK],
    [GENRE_METAL, GENRE_METAL],
]

BILLBOARD_CHART_ROCK = 'rock'
BILLBOARD_CHART_ALTERNATIVE = 'alternative'
BILLBOARD_CHART_HARD_ROCK = 'hard rock'
BILLBOARD_CHART_CHRISTIAN = 'christian'

BILLBOARD_CHOICES = [
    [BILLBOARD_CHART_ROCK, BILLBOARD_CHART_ROCK],
    [BILLBOARD_CHART_ALTERNATIVE, BILLBOARD_CHART_ALTERNATIVE],
    [BILLBOARD_CHART_HARD_ROCK, BILLBOARD_CHART_HARD_ROCK],
    [BILLBOARD_CHART_CHRISTIAN, BILLBOARD_CHART_CHRISTIAN],
]

BILLBOARD_CHART_URLS = {
    BILLBOARD_CHART_ROCK: 'https://www.billboard.com/charts/rock-albums/',
    BILLBOARD_CHART_ALTERNATIVE: 'https://www.billboard.com/charts/alternative-albums/',
    BILLBOARD_CHART_HARD_ROCK: 'https://www.billboard.com/charts/hard-rock-albums/',
    BILLBOARD_CHART_CHRISTIAN: 'https://www.billboard.com/charts/christian-albums/',
}

AZLYRICS_ARTISTS = {
    'aperfectcircle': 'perfectcircle',
    'matchboxtwenty': 'matchbox20',
    'thirtysecondstomars': '30secondstomars',
    'u2': 'u2band',
}

AZLYRICS_SONGS = {
    '4wallsfuneral': 'fourwalls',  # staind
    '7chinesebros': 'sevenchinesebrothers',  # REM
    'allapologies': 'allapologies112595',  # nirvana
    'allfallsdown': 'allfalldown',  # machine head
    'allineedtoknow': 'allineednow',  # thousand foot krutch
    'astralromance': 'astralromance129996',  # nightwish
    'becoming': 'becoming130138',  # pantera
    'bettermanthecage': 'betterman',  # oasis
    'burningthemaps': 'burningthemap',  # better than ezra
    'caughtalitesneeze': 'caughtalightsneeze',  # evans blue
    'comebackaround': 'comebackaround28977',  # feeder
    'daddyuntitled': 'daddy',  # korn
    'getthruthis': 'getthroughthis',  # art of dying
    'gimmestitches': 'gimmiestitches',  # foo fighters
    'highanddry': 'highdry',  # radiohead
    'illattack': 'attack',  # thrirty seconds to mars
    'ishfwilf': 'istillhaventfoundwhatimlookingforishfwilf',  # disturbed
    'mudshuvel': 'mudshovel',  # staind
    'pinata': 'piata',  # chevelle
    'qthebestoneofourlives': 'q',  # evans blue
    'reprisesandblastedskin': 'sandblastedskin',  # pantera
    'riptideedit': 'riptide',  # sick puppies
    'thebeatgoeson': 'beatgoeson',  # britney spears
    'tumbleandfall': 'tumblefall',  # feeder
    'voodoowitchhunt': 'voodoo',  # godsmack
    'war': 'streetfighterwar',  # sick puppies
}

AZLYRICS_INSTRUMENTALS = [
    'disturbed-remnants',
    'nightwish-moondance',
    'linkin park-fromzero',
    'puddle of mudd-welcometogalvania',
    'nickelback-thebetrayalacti',
    'popevil-instrumental',
]
