RATINGS_WINDOW = 60 * 40  # minutes

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
    '5minutesalone': '5minutesalone130139',  # pantera
    '7chinesebros': 'sevenchinesebrothers',  # REM
    'allapologies': 'allapologies112595',  # nirvana
    'allfallsdown': 'allfalldown',  # machine head
    'allineedtoknow': 'allineednow',  # thousand foot krutch
    'allthoseyesterdayshummus': 'allthoseyesterdays',  # pearl jam
    'amurderofone': 'murderofone',  # counting crows
    'astralromance': 'astralromance129996',  # nightwish
    'beautifulskyfeatjimjames': 'beautifulsky',  # semisonic
    'becoming': 'becoming130138',  # pantera
    'bendandbreak': 'bendbreak',  # keane
    'bettermanthecage': 'betterman',  # oasis
    'blew': 'blew112537',  # nirvana
    'burningthemaps': 'burningthemap',  # better than ezra
    'caughtalitesneeze': 'caughtalightsneeze',  # evans blue
    'comebackaround': 'comebackaround28977',  # feeder
    'daddyuntitled': 'daddy',  # korn
    'darwintheredsummersunextendedcoda': 'redsummersun',  # third eye blind
    'dumb': 'dumb112602',  # nirvana
    'getthruthis': 'getthroughthis',  # art of dying
    'gimmestitches': 'gimmiestitches',  # foo fighters
    'highanddry': 'highdry',  # radiohead
    'illattack': 'attack',  # thrirty seconds to mars
    'imbroken': 'imbroken130140',  # pantera
    'ishfwilf': 'istillhaventfoundwhatimlookingforishfwilf',  # disturbed
    'jesusdoesntwantmeforasunbeam': 'jesusdontwantmeforasunbeam',  # nirvana
    'keepawayacoustic': 'keepaway',  # godsmack
    'ko': 'k',  # korn
    'mfc': 'mfcminifastcar',  # pearl jam
    'mudshuvel': 'mudshovel',  # staind
    'oceansandstreams': 'oceansstreams',  # the black keys
    'peaceloveandunderstanding': 'whatssofunnyboutpeaceloveandunderstanding',  # a perfect circle
    'pictureperfectinyoureyesplanets2': 'pictureperfectinyoureyes',  # 10 years
    'pinata': 'piata',  # chevelle
    'qthebestoneofourlives': 'q',  # evans blue
    'realignacoustic': 'realign',  # godsmack
    'reprisesandblastedskin': 'sandblastedskin',  # pantera
    'riptideedit': 'riptide',  # sick puppies
    'thesirenscall': 'sirenscall',  # live
    'smashcomeoutandplayreprise': 'smash',  # the offspring
    'spiralacoustic': 'spiral',  # godsmack
    'strobinsoninhiscadillacdream': 'saintrobinsoninhiscadillacdream',  # counting crows
    'stirbnichtvormirdontdiebeforeido': 'stirbnichtvormir',  # rammstein
    'strengthbeyondstrength': 'strengthbeyondstrength130137',  # pantera
    'thebeatgoeson': 'beatgoeson',  # britney spears
    'thepeoplethatwelove': 'thepeoplethatwelovespeedkills',  # bush
    'tumbleandfall': 'tumblefall',  # feeder
    'voicesacoustic': 'voices',  # godsmack
    'voodoowitchhunt': 'voodoo',  # godsmack
    'war': 'streetfighterwar',  # sick puppies
    'whoreallycaresfeaturingthesoundofinsanity': 'whoreallycares',  # powderfinger
}
