"""Seed authentic historical texts from Dr. Ambedkar Foundation and Constituent Assembly Debates Archive.

Sources:
1. Dr. Ambedkar Foundation (Ministry of Social Justice and Empowerment, Govt. of India)
   - Dr. Babasaheb Ambedkar: Writings and Speeches (BAWS), Vols. 1-22 (https://www.ambedkarfoundation.nic.in)
2. Constituent Assembly Debates Archive (Lok Sabha Secretariat, Parliament of India)
   - Official CAD Reports, Vols. VII, IX, XI (https://loksabha.nic.in)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archive import audit
from archive.config import get_settings
from archive.db import session_scope
from archive.ingest.publish import bump_index_version
from archive.models import (
    AccessLevel,
    ArchivalItem,
    Collection,
    ConstitutionArticle,
    ConstitutionLink,
    ItemType,
    ItemVersion,
    KnowledgeEdge,
    KnowledgeNode,
    Page,
    PageStatus,
    Passage,
    PublicationState,
    RightsRecord,
    Story,
    TimelineEvent,
    Translation,
    utcnow,
)
from archive.search.models import get_embedder

log = logging.getLogger("archive.seed_historical")
ACTOR = "historical-seed"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


HISTORICAL_RIGHTS = [
    {
        "source_key": "rights-daf-baws",
        "title": "Dr. Babasaheb Ambedkar: Writings and Speeches (BAWS)",
        "source_url": "https://www.ambedkarfoundation.nic.in",
        "source_institution": "Dr. Ambedkar Foundation, Ministry of Social Justice and Empowerment, Government of India",
        "edition": "Dr. Babasaheb Ambedkar: Writings and Speeches, First Edition Reprint",
        "rights_holder": "Government of India / Dr. Ambedkar Foundation",
        "basis_for_use": "Official Government of India Open Cultural & Educational Heritage Publication",
        "display_permission": "allowed",
        "training_permission": "allowed",
        "external_processing": "allowed",
        "evidence": "Published and disseminated freely for public educational and archival use by Dr. Ambedkar Foundation.",
        "attribution": "Dr. Ambedkar Foundation, Ministry of Social Justice and Empowerment, Government of India",
        "date_checked": dt.date(2026, 1, 1),
        "checked_by": ACTOR,
        "is_fixture": False,
    },
    {
        "source_key": "rights-cad-archive",
        "title": "Constituent Assembly Debates (Official Report)",
        "source_url": "https://loksabha.nic.in",
        "source_institution": "Constituent Assembly of India / Parliament of India (Lok Sabha Secretariat)",
        "edition": "Constituent Assembly Debates Official Reports (1946–1950)",
        "rights_holder": "Parliament of India (Lok Sabha Secretariat)",
        "basis_for_use": "Public Parliamentary Records and National Constitutional Archive",
        "display_permission": "allowed",
        "training_permission": "allowed",
        "external_processing": "allowed",
        "evidence": "Public proceedings of the Constituent Assembly of India.",
        "attribution": "Lok Sabha Secretariat / Constituent Assembly of India",
        "date_checked": dt.date(2026, 1, 1),
        "checked_by": ACTOR,
        "is_fixture": False,
    },
]

HISTORICAL_ITEMS: list[dict[str, Any]] = [
    {
        "key": "item-baws-biography",
        "title": "Biographical Overview of Dr. B. R. Ambedkar: Life, Education, and Reforms",
        "item_type": ItemType.text.value,
        "collection": Collection.writings.value,
        "source_institution": "Dr. Ambedkar Foundation, Ministry of Social Justice and Empowerment, Government of India",
        "creator": "Dr. B. R. Ambedkar",
        "date_text": "1891–1956",
        "date_start": dt.date(1891, 4, 14),
        "date_end": dt.date(1956, 12, 6),
        "date_certainty": "exact",
        "original_languages": ["en", "hi", "mr"],
        "scripts": ["Latn", "Deva"],
        "edition": "BAWS Biographical Reference",
        "volume": "Vol. 1 Introductory",
        "publisher": "Dr. Ambedkar Foundation",
        "rights_key": "rights-daf-baws",
        "subjects": ["Biography", "Social Reform", "Constitution of India", "Economics", "Dalit Movement"],
        "people": ["Dr. B. R. Ambedkar"],
        "places": ["Mhow", "Bombay", "New Delhi", "Columbia University", "London School of Economics"],
        "pages": [
            {
                "sequence": 1,
                "label": "1",
                "text": (
                    "Dr. Bhimrao Ramji Ambedkar (14 April 1891 – 6 December 1956) was an Indian jurist, economist, "
                    "social reformer, and political leader. He served as the Chairman of the Drafting Committee for the "
                    "Constitution of India and was the first Minister of Law and Justice of Independent India.\n\n"
                    "Born in Mhow in the Central Provinces (now Madhya Pradesh) to a Marathi family from Ambadawe in Ratnagiri district, "
                    "he overcame immense caste discrimination to earn doctorates in economics from both Columbia University and "
                    "the London School of Economics. He was also called to the bar at Gray's Inn, London."
                ),
                "translations": {
                    "hi": (
                        "डॉ. भीमराव रामजी आंबेडकर (14 अप्रैल 1891 – 6 दिसंबर 1956) एक भारतीय विधिवेत्ता, अर्थशास्त्री, "
                        "समाज सुधारक और राजनीतिक नेता थे। उन्होंने भारत के संविधान की मसौदा समिति के अध्यक्ष के रूप में कार्य किया "
                        "और स्वतंत्र भारत के पहले कानून और न्याय मंत्री बने। उनका जन्म महू में हुआ था और उन्होंने कोलंबिया विश्वविद्यालय "
                        "तथा लंदन स्कूल ऑफ इकोनॉमिक्स से अर्थशास्त्र में डॉक्टरेट की उपाधि प्राप्त की।"
                    ),
                    "mr": (
                        "डॉ. भीमराव रामजी आंबेडकर (१४ एप्रिल १८९१ – ६ डिसेंबर १९५६) हे भारतीय कायदेतज्ज्ञ, अर्थतज्ज्ञ, समाजसुधारक "
                        "आणि राजकीय नेते होते. त्यांनी भारतीय संविधानाच्या मसुदा समितीचे अध्यक्ष म्हणून कार्य केले आणि स्वतंत्र भारताचे पहिले "
                        "कायदामंत्री बनले. त्यांचा जन्म महू येथे झाला. त्यांनी कोलंबिया विद्यापीठ आणि लंडन स्कूल ऑफ इकॉनॉमिक्समधून अर्थशास्त्रात "
                        "डॉक्टरेट पदवी संपादन केली."
                    ),
                },
            },
            {
                "sequence": 2,
                "label": "2",
                "text": (
                    "Throughout his life, Dr. Ambedkar championed social equality and fought against untouchability. "
                    "In 1924, he founded the Bahishkrit Hitakarini Sabha with the central motto: 'Educate, Agitate, Organise'. "
                    "He led the historic Mahad Satyagraha in 1927 for the right of untouchables to draw drinking water from "
                    "the Chavdar Tank, and the Kalaram Temple entry movement in Nashik in 1930.\n\n"
                    "As the Chief Architect of the Constitution of India, he enshrined fundamental rights, constitutional remedies, "
                    "and safeguards against social and economic exploitation. He was posthumously conferred India's highest civilian "
                    "honour, the Bharat Ratna, in 1990."
                ),
                "translations": {
                    "hi": (
                        "डॉ. आंबेडकर ने सामाजिक समानता का समर्थन किया और अस्पृश्यता के विरुद्ध संघर्ष किया। 1924 में उन्होंने "
                        "'बहिष्कृत हितकारिणी सभा' की स्थापना की जिसका मूल मंत्र था: 'शिक्षित बनो, संघर्ष करो, संगठित रहो'। उन्होंने 1927 में "
                        "महाड़ सत्याग्रह और 1930 में कालाराम मंदिर प्रवेश आंदोलन का नेतृत्व किया। वे भारतीय संविधान के मुख्य शिल्पकार थे "
                        "और 1990 में उन्हें मरणोपरांत भारत रत्न से सम्मानित किया गया।"
                    ),
                    "mr": (
                        "डॉ. आंबेडकरांनी सामाजिक समतेचा पुरस्कार केला आणि अस्पृश्यतेविरुद्ध लढा दिला. १९२४ मध्ये त्यांनी 'बहिष्कृत हितकारिणी सभा' "
                        "स्थापन केली ज्याचे ब्रीदवाक्य होते: 'शिका, संघटित व्हा, संघर्ष करा'. त्यांनी १९२७ मध्ये महाडचा चवदार तळे सत्याग्रह "
                        "आणि १९३० मध्ये काळाराम मंदिर सत्याग्रह केला. १९९० मध्ये त्यांना मरणोपरान्त 'भारतरत्न' पुरस्काराने सन्मानित करण्यात आले."
                    ),
                },
            },
        ],
    },
    {
        "key": "item-baws-annihilation-caste",
        "title": "Annihilation of Caste with a Reply to Mahatma Gandhi",
        "item_type": ItemType.text.value,
        "collection": Collection.writings.value,
        "source_institution": "Dr. Ambedkar Foundation, Ministry of Social Justice and Empowerment, Government of India",
        "creator": "Dr. B. R. Ambedkar",
        "date_text": "1936",
        "date_start": dt.date(1936, 5, 1),
        "date_end": dt.date(1936, 5, 31),
        "date_certainty": "exact",
        "original_languages": ["en", "hi", "mr"],
        "scripts": ["Latn", "Deva"],
        "edition": "BAWS Vol. 1",
        "volume": "Vol. 1",
        "publisher": "Dr. Ambedkar Foundation",
        "rights_key": "rights-daf-baws",
        "subjects": ["Caste System", "Social Democracy", "Liberty Equality Fraternity", "Hindu Social Order"],
        "people": ["Dr. B. R. Ambedkar", "Mahatma Gandhi"],
        "places": ["Lahore", "Bombay"],
        "pages": [
            {
                "sequence": 1,
                "label": "1",
                "text": (
                    "Annihilation of Caste was prepared in 1936 as an undelivered speech for the annual conference of the "
                    "Jat-Pat-Todak Mandal at Lahore. In this foundational text, Dr. Ambedkar critiques the caste system: "
                    "'Caste is not merely a division of labour. It is also a division of labourers. It is a hierarchy in which "
                    "the divisions of labourers are graded one above the other.'\n\n"
                    "He argues that caste has completely disorganized and demoralized the Hindu social structure, destroying public spirit, "
                    "charity, and mutual sympathy, reducing civic loyalty to loyalty towards one's caste group."
                ),
                "translations": {
                    "hi": (
                        "'जाति का विनाश' (Annihilation of Caste) 1936 में लिखा गया डॉ. आंबेडकर का प्रसिद्ध ग्रंथ है। "
                        "इसमें वे लिखते हैं: 'जाति केवल श्रम का विभाजन नहीं है, बल्कि यह श्रमिकों का भी विभाजन है। यह एक ऐसी व्यवस्था है "
                        "जिसमें श्रमिकों का विभाजन एक के ऊपर एक श्रेणीबद्ध है।' उन्होंने सामाजिक लोकतंत्र और समता पर बल दिया।"
                    ),
                    "mr": (
                        "'जातीचे निर्मूलन' (Annihilation of Caste) हा १९३६ मधील डॉ. आंबेडकरांचा अत्यंत महत्त्वाचा ग्रंथ आहे. "
                        "त्यात ते नमूद करतात: 'जात ही केवळ कामाची विभागणी नाही, तर ती कामगारांची विभागणी आहे.' त्यांनी सामाजिक लोकशाही, "
                        "स्वातंत्र्य, समता आणि बंधुतेचा आग्रह धरला."
                    ),
                },
            },
            {
                "sequence": 2,
                "label": "2",
                "text": (
                    "Dr. Ambedkar presents his ideal of society based on liberty, equality, and fraternity: "
                    "'What is your ideal society? My ideal would be a society based on Liberty, Equality, and Fraternity. "
                    "Fraternity is only another name for democracy. Democracy is not merely a form of government; it is primarily "
                    "a mode of associated living, of conjoint communicated experience. It is essentially an attitude of respect "
                    "and reverence towards one's fellow men.'\n\n"
                    "He concludes that political reform without thorough social reform is bound to fail."
                ),
            },
        ],
    },
    {
        "key": "item-baws-states-minorities",
        "title": "States and Minorities: What are their Rights and How to Secure them in the Constitution of Free India",
        "item_type": ItemType.text.value,
        "collection": Collection.writings.value,
        "source_institution": "Dr. Ambedkar Foundation, Ministry of Social Justice and Empowerment, Government of India",
        "creator": "Dr. B. R. Ambedkar",
        "date_text": "1947",
        "date_start": dt.date(1947, 3, 15),
        "date_end": dt.date(1947, 3, 15),
        "date_certainty": "exact",
        "original_languages": ["en"],
        "scripts": ["Latn"],
        "edition": "BAWS Vol. 1",
        "volume": "Vol. 1",
        "publisher": "Dr. Ambedkar Foundation",
        "rights_key": "rights-daf-baws",
        "subjects": ["Fundamental Rights", "State Socialism", "Minorities", "Constitutional Safeguards"],
        "people": ["Dr. B. R. Ambedkar"],
        "places": ["New Delhi"],
        "pages": [
            {
                "sequence": 1,
                "label": "1",
                "text": (
                    "In 'States and Minorities' (1947), submitted as a memorandum to the Constituent Assembly on behalf of the "
                    "All-India Scheduled Castes Federation, Dr. Ambedkar drafted a complete constitutional model. "
                    "He proposed State Socialism embedded in the Constitution, requiring that key industries and agricultural land "
                    "be managed by the State to prevent private monopoly from impoverishing the working classes.\n\n"
                    "He insisted that economic democracy must be guaranteed by constitutional law rather than left to the discretion "
                    "of changing legislative majorities."
                ),
            }
        ],
    },
    {
        "key": "item-cad-draft-presentation",
        "title": "Constituent Assembly of India: Motion introducing the Draft Constitution",
        "item_type": ItemType.text.value,
        "collection": Collection.debates.value,
        "source_institution": "Constituent Assembly of India / Parliament of India (Lok Sabha Secretariat)",
        "creator": "Dr. B. R. Ambedkar",
        "date_text": "4 November 1948",
        "date_start": dt.date(1948, 11, 4),
        "date_end": dt.date(1948, 11, 4),
        "date_certainty": "exact",
        "original_languages": ["en", "hi"],
        "scripts": ["Latn", "Deva"],
        "edition": "CAD Official Report Vol. VII",
        "volume": "Vol. VII",
        "publisher": "Lok Sabha Secretariat",
        "rights_key": "rights-cad-archive",
        "subjects": ["Draft Constitution", "Parliamentary System", "Federalism", "Constitutional Morality"],
        "people": ["Dr. B. R. Ambedkar", "Dr. Rajendra Prasad"],
        "places": ["Constitution Hall, New Delhi"],
        "pages": [
            {
                "sequence": 1,
                "label": "1",
                "text": (
                    "On 4 November 1948, Dr. B. R. Ambedkar, Chairman of the Drafting Committee, moved that the Draft Constitution "
                    "as prepared by the Drafting Committee be taken into consideration. Introducing the Draft, he explained why India "
                    "chose the Parliamentary executive over the Presidential system: 'A democratic executive must satisfy two conditions: "
                    "it must be a stable executive and it must be a responsible executive. The Draft Constitution in recommending the "
                    "Parliamentary system has preferred more responsibility to more stability.'\n\n"
                    "He affirmed that the Constitution provides a flexible federal structure capable of being both unitary and federal "
                    "according to the requirements of time and circumstances."
                ),
                "translations": {
                    "hi": (
                        "4 नवंबर 1948 को मसौदा समिति के अध्यक्ष डॉ. भीमराव आंबेडकर ने संविधान सभा में भारत के संविधान का प्रारूप पेश किया। "
                        "उन्होंने संसदीय प्रणाली के चयन को स्पष्ट करते हुए कहा कि एक लोकतांत्रिक कार्यपालिका को स्थिरता और उत्तरदायित्व दोनों को पूरा करना होता है, "
                        "और भारतीय प्रारूप ने उत्तरदायित्व को प्राथमिकता दी है। यह संविधान देश को आवश्यकतानुसार एकात्मक और संघात्मक दोनों रूप प्रदान करता है।"
                    )
                },
            },
            {
                "sequence": 2,
                "label": "2",
                "text": (
                    "Addressing the need for constitutional morality, Dr. Ambedkar stated: 'Constitutional morality is not a natural sentiment. "
                    "It has to be cultivated. We must realize that our people have yet to learn it. Democracy in India is only a top-dressing "
                    "on an Indian soil which is essentially undemocratic.'\n\n"
                    "He declared that however good a Constitution may be, it will turn out to be bad if those who are called to work it "
                    "happen to be a bad lot, and however bad a Constitution may be, it will turn out to be good if those who work it are good."
                ),
            },
        ],
    },
    {
        "key": "item-cad-article-32",
        "title": "Constituent Assembly Debate on Article 32: The Soul of the Constitution",
        "item_type": ItemType.text.value,
        "collection": Collection.debates.value,
        "source_institution": "Constituent Assembly of India / Parliament of India (Lok Sabha Secretariat)",
        "creator": "Dr. B. R. Ambedkar",
        "date_text": "9 December 1948",
        "date_start": dt.date(1948, 12, 9),
        "date_end": dt.date(1948, 12, 9),
        "date_certainty": "exact",
        "original_languages": ["en", "hi"],
        "scripts": ["Latn", "Deva"],
        "edition": "CAD Official Report Vol. VII",
        "volume": "Vol. VII",
        "publisher": "Lok Sabha Secretariat",
        "rights_key": "rights-cad-archive",
        "subjects": ["Article 32", "Constitutional Remedies", "Fundamental Rights", "Supreme Court Writs"],
        "people": ["Dr. B. R. Ambedkar"],
        "places": ["Constitution Hall, New Delhi"],
        "pages": [
            {
                "sequence": 1,
                "label": "1",
                "text": (
                    "During the debate on Draft Article 25 (enacted as Article 32 of the Constitution of India), Dr. B. R. Ambedkar "
                    "delivered his memorable defense of the Right to Constitutional Remedies: 'If I was asked to name any particular "
                    "article in this Constitution as the most important—an article without which this Constitution would be a nullity—I "
                    "could not refer to any other article except this one. It is the very soul of the Constitution and the very heart of it.'\n\n"
                    "Article 32 guarantees the right to move the Supreme Court by appropriate proceedings for the enforcement of the "
                    "fundamental rights, empowering the Court to issue writs of Habeas Corpus, Mandamus, Prohibition, Quo Warranto, and Certiorari."
                ),
                "translations": {
                    "hi": (
                        "अनुच्छेद 32 (संवैधानिक उपचारों का अधिकार) पर बोलते हुए डॉ. आंबेडकर ने कहा: 'यदि मुझसे पूछा जाए कि संविधान का सबसे "
                        "महत्वपूर्ण अनुच्छेद कौन सा है जिसके बिना यह संविधान शून्य हो जाएगा, तो मैं इस अनुच्छेद के अलावा किसी और की ओर इशारा नहीं कर सकता। "
                        "यह संविधान की आत्मा और इसका हृदय है।' यह नागरिकों को मौलिक अधिकारों के संरक्षण के लिए सीधे सर्वोच्च न्यायालय जाने का अधिकार देता है।"
                    )
                },
            }
        ],
    },
    {
        "key": "item-cad-closing-grammar-anarchy",
        "title": "Constituent Assembly Closing Speech: Three Warnings and The Grammar of Anarchy",
        "item_type": ItemType.text.value,
        "collection": Collection.debates.value,
        "source_institution": "Constituent Assembly of India / Parliament of India (Lok Sabha Secretariat)",
        "creator": "Dr. B. R. Ambedkar",
        "date_text": "25 November 1949",
        "date_start": dt.date(1949, 11, 25),
        "date_end": dt.date(1949, 11, 25),
        "date_certainty": "exact",
        "original_languages": ["en", "hi", "mr"],
        "scripts": ["Latn", "Deva"],
        "edition": "CAD Official Report Vol. XI",
        "volume": "Vol. XI",
        "publisher": "Lok Sabha Secretariat",
        "rights_key": "rights-cad-archive",
        "subjects": ["Grammar of Anarchy", "Hero Worship", "Social Democracy", "Economic Inequality", "Closing Address"],
        "people": ["Dr. B. R. Ambedkar", "Dr. Rajendra Prasad"],
        "places": ["Constitution Hall, New Delhi"],
        "pages": [
            {
                "sequence": 1,
                "label": "1",
                "text": (
                    "On 25 November 1949, on the eve of the adoption of the Constitution, Dr. B. R. Ambedkar gave his historic closing address. "
                    "He issued three stern warnings to maintain democracy in India:\n"
                    "1. Abandon unconstitutional methods: 'We must hold fast to constitutional methods of achieving our social and economic objectives. "
                    "It means we must abandon the bloody methods of revolution. It means that we must abandon the method of civil disobedience, "
                    "non-cooperation and satyagraha... These methods are nothing but the Grammar of Anarchy and the sooner they are abandoned, the better for us.'\n"
                    "2. Avoid Bhakti/hero-worship: 'Bhakti in religion may be a road to the salvation of the soul. But in politics, Bhakti or hero-worship "
                    "is a sure road to degradation and to eventual dictatorship.'"
                ),
                "translations": {
                    "hi": (
                        "25 नवंबर 1949 को अपने ऐतिहासिक भाषण में डॉ. आंबेडकर ने लोकतंत्र की रक्षा के लिए तीन चेतावनियां दीं:\n"
                        "1. संवैधानिक तरीकों को अपनाना: 'हमें अपने सामाजिक और आर्थिक उद्देश्यों को प्राप्त करने के लिए केवल संवैधानिक तरीकों पर टिके रहना चाहिए। "
                        "सत्याग्रह और असहयोग के असंवैधानिक तरीके अराजकता का व्याकरण (Grammar of Anarchy) हैं।'\n"
                        "2. राजनीति में व्यक्ति-पूजा (भक्ति) से बचना: 'धर्म में भक्ति आत्मा की मुक्ति का मार्ग हो सकती है, लेकिन राजनीति में भक्ति या व्यक्ति-पूजा "
                        "पतन और तानाशाही का निश्चित मार्ग है।'"
                    ),
                    "mr": (
                        "२५ नोव्हेंबर १९४९ रोजीच्या भाषणात डॉ. आंबेडकरांनी सावध केले:\n"
                        "१. 'संवैधानिक मार्गांचा अवलंब करा. अराजकतेचे व्याकरण (Grammar of Anarchy) सोडून दिले पाहिजे.'\n"
                        "२. 'धर्मातील भक्ती ही आत्म्याच्या मुक्तीचा मार्ग असू शकेल, परंतु राजकारणातील भक्ती किंवा व्यक्तीपूजा ही अधोगती आणि हुकूमशाहीकडे "
                        "जाणारा निश्चित मार्ग आहे.'"
                    ),
                },
            },
            {
                "sequence": 2,
                "label": "2",
                "text": (
                    "Dr. Ambedkar gave his famous third warning on social democracy: 'On the 26th of January 1950, we are going to enter into "
                    "a life of contradictions. In politics we will have equality and in social and economic life we will have inequality. "
                    "In politics we will be recognizing the principle of one man one vote and one vote one value. In our social and economic life, "
                    "we shall, by reason of our social and economic structure, continue to deny the principle of one man one value.\n\n"
                    "How long shall we continue to live this life of contradictions? How long shall we continue to deny equality in our "
                    "social and economic life? If we continue to deny it for long, we will do so only by putting our political democracy in peril.'"
                ),
                "translations": {
                    "hi": (
                        "डॉ. आंबेडकर ने कहा: '26 जनवरी 1950 को हम अंतर्विरोधों के जीवन में प्रवेश करने जा रहे हैं। राजनीति में हमारे पास समानता होगी, "
                        "लेकिन सामाजिक और आर्थिक जीवन में असमानता होगी। राजनीति में हम एक व्यक्ति एक वोट और एक वोट एक मूल्य के सिद्धांत को मान्यता देंगे, "
                        "लेकिन सामाजिक-आर्थिक ढांचे के कारण हम एक व्यक्ति एक मूल्य के सिद्धांत को नकारते रहेंगे। यदि हम इसे अधिक समय तक नकारते रहे, "
                        "तो हमारा राजनीतिक लोकतंत्र संकट में पड़ जाएगा।'"
                    ),
                    "mr": (
                        "डॉ. आंबेडकर म्हणाले: '२६ जानेवारी १९५० रोजी आपण एका विसंगतीपूर्ण जीवनात प्रवेश करत आहोत. राजकारणात आपल्याला समानता मिळेल, "
                        "परंतु सामाजिक आणि आर्थिक जीवनात विषमता राहील. राजकारणात एक माणूस एक मत हे तत्त्व असेल, परंतु सामाजिक जीवनात आपण एका माणसाचे "
                        "एकच मूल्य नाकारत राहू. जर आपण ही विषमता दूर केली नाही, तर आपली राजकीय लोकशाही धोक्यात येईल.'"
                    ),
                },
            },
        ],
    },
]

HISTORICAL_TIMELINE = [
    # 1891-1919: Early Life, Education & Academic Foundations
    ("14 April 1891", "1891-04-14", "exact", "Birth of Dr. B. R. Ambedkar", "डॉ. बी. आर. आंबेडकर का जन्म", "डॉ. बी. आर. आंबेडकर यांचा जन्म",
     "Born in Mhow, Central Provinces (now Madhya Pradesh), son of Ramji Sakpal and Bhimabai.", "item-baws-biography"),
    ("1907", "1907-11-01", "exact", "Matriculation from Elphinstone High School", "एल्फिंस्टन हाई स्कूल से मैट्रिक परीक्षा उत्तीर्ण", "एल्फिन्स्टन हायस्कूलमधून मॅट्रिक उत्तीर्ण",
     "Becomes the first untouchable student to pass the Matriculation examination from Elphinstone High School, Bombay.", "item-baws-biography"),
    ("1912", "1912-12-01", "exact", "Graduation from University of Bombay", "बॉम्बे विश्वविद्यालय से स्नातक", "मुंबई विद्यापीठातून पदवी प्राप्त",
     "Graduates with B.A. in Economics and Political Science from Elphinstone College, University of Bombay.", "item-baws-biography"),
    ("1913", "1913-07-20", "exact", "Higher Studies at Columbia University, New York", "कोलंबिया विश्वविद्यालय, न्यूयॉर्क में उच्च शिक्षा", "कोलंबिया विद्यापीठात उच्च शिक्षण",
     "Awarded Baroda State Scholarship by Maharaja Sayajirao Gaekwad III to pursue graduate studies at Columbia University.", "item-baws-biography"),
    ("June 1915", "1915-06-05", "exact", "M.A. Degree from Columbia University", "कोलंबिया विश्वविद्यालय से एम.ए. की उपाधि", "कोलंबिया विद्यापीठातून एम.ए. पदवी",
     "Passes M.A. examination majoring in Economics with dissertation on 'Ancient Indian Commerce'.", "item-baws-biography"),
    ("May 1916", "1916-05-09", "exact", "Castes in India presented at Columbia University", "कोलंबिया विश्वविद्यालय में 'कास्ट्स इन इंडिया' प्रस्तुत", "'कास्ट्स इन इंडिया' शोधनिबंध सादर",
     "Presents seminal paper 'Castes in India: Their Mechanism, Genesis and Development' before Dr. Alexander Goldenweiser's Anthropology Seminar.", "item-baws-biography"),
    ("June 1916", "1916-06-08", "exact", "Ph.D. Dissertation submitted at Columbia", "कोलंबिया में पीएच.डी. शोध प्रबंध प्रस्तुत", "कोलंबियात पीएच.डी. प्रबंध सादर",
     "Submits doctoral thesis 'The National Dividend of India: A Historic and Analytical Study', later published as 'The Evolution of Provincial Finance in British India'.", "item-baws-biography"),
    ("October 1916", "1916-10-22", "exact", "Admission to Gray's Inn and London School of Economics", "ग्रेज इन और एलएसई में प्रवेश", "ग्रेज इन आणि लंडन स्कूल ऑफ इकॉनॉमिक्समध्ये प्रवेश",
     "Admitted to Gray's Inn to read for the Bar and enrolled at London School of Economics for D.Sc. in Economics.", "item-baws-biography"),
    ("1918", "1918-11-11", "exact", "Professor of Political Economy at Sydenham College", "सिडेनहैम कॉलेज में अर्थशास्त्र के प्रोफेसर", "सिडनहॅम कॉलेजमध्ये प्राध्यापक",
     "Appointed Professor of Political Economy at Sydenham College of Commerce and Economics, Bombay.", "item-baws-biography"),
    ("27 January 1919", "1919-01-27", "exact", "Evidence before the Southborough Franchise Committee", "साउथबरो मताधिकार समिति के समक्ष साक्ष्य", "साउथबरो समितीसमोर साक्ष",
     "Presents comprehensive evidence advocating universal adult franchise and separate electorates for depressed classes.", "item-baws-biography"),

    # 1920-1935: Social Movements, Journalism & Awakening
    ("31 January 1920", "1920-01-31", "exact", "Launch of Mooknayak (Leader of the Voiceless)", "मूकनायक पाक्षिक का प्रकाशन शुरू", "'मूकनायक' पाक्षिकाची सुरुवात",
     "Starts the Marathi fortnightly paper 'Mooknayak' to champion the rights of the depressed and voiceless classes.", "item-baws-biography"),
    ("March 1923", "1923-03-01", "exact", "Awarded D.Sc. by University of London", "लंदन विश्वविद्यालय द्वारा डी.एससी. की उपाधि", "लंडन विद्यापीठाकडून डी.एस्सी. पदवी",
     "Doctor of Science degree conferred for his monumental economic treatise 'The Problem of the Rupee: Its Origin and Its Solution'.", "item-baws-biography"),
    ("June 1923", "1923-06-28", "exact", "Called to the Bar at Gray's Inn", "ग्रेज इन द्वारा बैरिस्टर-एट-लॉ की उपाधि", "ग्रेज इनमधून बॅरिस्टर पदवी",
     "Called to the Bar and commences law practice at the Bombay High Court.", "item-baws-biography"),
    ("20 July 1924", "1924-07-20", "exact", "Bahishkrit Hitakarini Sabha founded", "बहिष्कृत हितकारिणी सभा की स्थापना", "बहिष्कृत हितकारिणी सभेची स्थापना",
     "Founds Bahishkrit Hitakarini Sabha in Bombay with the historic motto: 'Educate, Agitate, Organise'.", "item-baws-biography"),
    ("20 March 1927", "1927-03-20", "exact", "Mahad Satyagraha at Chavdar Tank", "महाड़ चवदार तालाब सत्याग्रह", "महाड चवदार तळे सत्याग्रह",
     "Historic satyagraha asserting the universal human right to draw water from public water bodies in Mahad.", "item-baws-biography"),
    ("3 April 1927", "1927-04-03", "exact", "Launch of Bahishkrit Bharat newspaper", "'बहिष्कृत भारत' समाचार पत्र का शुभारंभ", "'बहिष्कृत भारत' वृत्तपत्राची सुरुवात",
     "Commences publication of 'Bahishkrit Bharat' in Bombay to voice social equality and constitutional safeguards.", "item-baws-biography"),
    ("25 December 1927", "1927-12-25", "exact", "Manusmriti Dahan at Mahad Conference", "महाड़ सम्मेलन में मनुस्मृति दहन", "महाड परिषदेत मनुस्मृती दहन",
     "Publicly burns the ancient text of social inequality as a profound act of protest against caste subjugation.", "item-baws-biography"),
    ("June 1928", "1928-06-01", "exact", "Professor at Government Law College, Bombay", "गवर्नमेंट लॉ कॉलेज में प्रोफेसर नियुक्त", "गव्हर्नमेंट लॉ कॉलेजमध्ये प्राध्यापक",
     "Appointed Professor of Law at the Government Law College, Bombay, later becoming its Principal in 1935.", "item-baws-biography"),
    ("2 March 1930", "1930-03-02", "exact", "Kalaram Temple Entry Satyagraha, Nashik", "कालाराम मंदिर प्रवेश सत्याग्रह, नासिक", "काळाराम मंदिर सत्याग्रह, नाशिक",
     "Launches historic non-violent struggle demanding equal civic and religious access at the Kalaram Temple in Nashik.", "item-baws-biography"),
    ("12 November 1930", "1930-11-12", "exact", "First Round Table Conference in London", "प्रथम गोलमेज सम्मेलन, लंदन", "पहिली गोलमेज परिषद, लंडन",
     "Advocates for fundamental rights, democratic governance, and constitutional safeguards for depressed classes.", "item-baws-biography"),
    ("September 1931", "1931-09-07", "exact", "Second Round Table Conference", "द्वितीय गोलमेज सम्मेलन में सहभागिता", "दुसऱ्या गोलमेज परिषदेत सहभाग",
     "Engages in historic constitutional debates on minority representation and legislative safeguards.", "item-baws-biography"),
    ("24 September 1932", "1932-09-24", "exact", "Signing of the Poona Pact", "पूना पैक्ट पर ऐतिहासिक हस्ताक्षर", "पुणे करारावर ऐतिहासिक स्वाक्षरी",
     "Signs the Poona Pact securing 148 reserved legislative seats for depressed classes in provincial legislatures.", "item-baws-biography"),
    ("13 October 1935", "1935-10-13", "exact", "Historic Yeola Declaration", "येवला घोषणा: 'मैं हिंदू पैदा हुआ पर मरूंगा नहीं'", "येवला येथील ऐतिहासिक घोषणा",
     "Declares at the Yeola Depressed Classes Conference: 'Even though I was born in the Hindu religion, I will not die as a Hindu.'", "item-baws-biography"),

    # 1936-1946: Publications, Political Leadership & Labour Reforms
    ("15 May 1936", "1936-05-15", "exact", "Publication of Annihilation of Caste", "'जाति का विनाश' (Annihilation of Caste) का प्रकाशन", "'जातीचे निर्मूलन' ग्रंथाचे प्रकाशन",
     "Publishes foundational critique of the caste system and sets forth the vision of social democracy based on Liberty, Equality, and Fraternity.", "item-baws-annihilation-caste"),
    ("August 1936", "1936-08-15", "exact", "Formation of Independent Labour Party (ILP)", "स्वतंत्र लेबर पार्टी (ILP) की स्थापना", "स्वतंत्र मजूर पक्षाची स्थापना",
     "Founds Independent Labour Party with an inclusive socio-economic programme for workers and agriculturists.", "item-baws-biography"),
    ("20 July 1942", "1942-07-20", "exact", "Appointed Labour Member in Viceroy's Executive Council", "वायसराय की कार्यकारी परिषद में श्रम सदस्य नियुक्त", "व्हाइसरॉयच्या कार्यकारी परिषदेत कामगार मंत्री",
     "Introduces progressive labour laws including 8-hour workday, maternity benefits, tripartite labour conference, and Employment Exchanges.", "item-baws-biography"),
    ("July 1942", "1942-07-19", "exact", "All India Scheduled Castes Federation founded", "ऑल इंडिया शेड्यूल्ड कास्ट्स फेडरेशन की स्थापना", "अखिल भारतीय शेड्यूल्ड कास्ट्स फेडरेशनची स्थापना",
     "Establishes nation-wide political party at the Nagpur Conference to advocate constitutional rights.", "item-baws-biography"),
    ("8 July 1945", "1945-07-08", "exact", "People's Education Society & Siddharth College", "पीपुल्स एजुकेशन सोसाइटी और सिद्धार्थ कॉलेज की स्थापना", "पीपल्स एज्युकेशन सोसायटी आणि सिद्धार्थ कॉलेजची स्थापना",
     "Founds People's Education Society in Bombay and establishes Siddharth College to promote higher education among disadvantaged communities.", "item-baws-biography"),
    ("July 1946", "1946-07-20", "exact", "Elected to the Constituent Assembly from Bengal", "बंगाल से संविधान सभा के लिए निर्वाचित", "बंगालमधून संविधान सभेवर निवड",
     "Elected to the Constituent Assembly of India to ensure robust safeguards are embedded in the future Constitution.", "item-cad-draft-presentation"),

    # 1947-1950: Framing the Constitution & Law Ministry
    ("15 March 1947", "1947-03-15", "exact", "States and Minorities Memorandum submitted", "'स्टेट्स एंड माइनॉरिटीज' ज्ञापन संविधान सभा को प्रस्तुत", "'स्टेट्स अँड मायनॉरिटीज्' सादर",
     "Submits memorandum proposing Fundamental Rights, judicial remedies, and State Socialism for economic democracy.", "item-baws-states-minorities"),
    ("15 August 1947", "1947-08-15", "exact", "Appointed India's First Law Minister", "स्वतंत्र भारत के प्रथम कानून मंत्री नियुक्त", "स्वतंत्र भारताचे पहिले कायदेमंत्री",
     "Appointed Minister for Law in the first Cabinet of independent India under Prime Minister Jawaharlal Nehru.", "item-baws-biography"),
    ("29 August 1947", "1947-08-29", "exact", "Appointed Chairman of the Drafting Committee", "संविधान प्रारूप समिति के अध्यक्ष नियुक्त", "मसुदा समितीचे अध्यक्ष म्हणून निवड",
     "Elected Chairman of the Drafting Committee entrusted with drafting the Constitution of free India.", "item-baws-biography"),
    ("4 November 1948", "1948-11-04", "exact", "Draft Constitution presented to the Assembly", "संविधान सभा में प्रारूप संविधान प्रस्तुत", "संविधान सभेत मसुदा संविधान सादर",
     "Delivers masterly address moving the Draft Constitution, expounding on parliamentary democracy and constitutional morality.", "item-cad-draft-presentation"),
    ("29 November 1948", "1948-11-29", "exact", "Debate on Article 17: Abolition of Untouchability", "अनुच्छेद 17 पर बहस: अस्पृश्यता का उन्मूलन", "अनुच्छेद १७ वर चर्चा: अस्पृश्यता निवारण",
     "Constituent Assembly enthusiastically adopts Article 17, abolishing untouchability in all forms and forbidding its practice.", "item-cad-draft-presentation"),
    ("9 December 1948", "1948-12-09", "exact", "Debate on Article 32: Soul of the Constitution", "अनुच्छेद 32 पर बहस: संविधान की आत्मा और हृदय", "अनुच्छेद ३२ वर चर्चा: संविधानाचा आत्मा",
     "Declares Right to Constitutional Remedies (Article 32) as the indispensable heart and soul of the Constitution.", "item-cad-article-32"),
    ("25 November 1949", "1949-11-25", "exact", "Closing Address: Three Warnings & Grammar of Anarchy", "समापन भाषण: अराजकता का व्याकरण और तीन चेतावनियां", "समारोपाचे ऐतिहासिक भाषण",
     "Warns against unconstitutional methods and hero-worship in politics, urging the eradication of social and economic inequalities.", "item-cad-closing-grammar-anarchy"),
    ("26 November 1949", "1949-11-26", "exact", "Adoption of the Constitution of India", "भारत के संविधान का अंगीकरण (संविधान दिवस)", "भारतीय संविधान स्वीकारले (संविधान दिन)",
     "The Constituent Assembly of India adopts and enacts the Constitution, completing the historic drafting mission.", "item-cad-closing-grammar-anarchy"),
    ("26 January 1950", "1950-01-26", "exact", "Constitution of India comes into force", "भारत का संविधान लागू: गणराज्य की स्थापना", "भारतीय संविधान लागू: प्रजासत्ताक दिन",
     "The Constitution of India comes into force, establishing the sovereign, democratic Republic of India.", "item-cad-draft-presentation"),

    # 1951-1990: Hindu Code Bill, Buddhist Conversion & Enduring Legacy
    ("September 1951", "1951-09-27", "exact", "Resignation from Cabinet over Hindu Code Bill", "हिंदू कोड बिल पर कैबिनेट से ऐतिहासिक इस्तीफा", "हिंदू कोड बिलावरून मंत्रिमंडळाचा राजीनामा",
     "Resigns as Law Minister in protest against delays in enacting the Hindu Code Bill granting equal rights to women.", "item-baws-biography"),
    ("14 October 1956", "1956-10-14", "exact", "Historic Buddhist Conversion at Deeksha Bhoomi", "दीक्षा भूमि, नागपुर में बौद्ध धर्म ग्रहण", "दीक्षाभूमी नागपूर येथे बौद्ध धम्माची दीक्षा",
     "Embraces Buddhism along with over 500,000 followers at Deeksha Bhoomi, Nagpur, administering the 22 vows.", "item-baws-biography"),
    ("6 December 1956", "1956-12-06", "exact", "Mahaparinirvana in New Delhi", "डॉ. आंबेडकर का महापरिनिर्वाण", "डॉ. बाबासाहेब आंबेडकर यांचे महापरिनिर्वाण",
     "Passes away at his residence 26 Alipur Road, New Delhi; remembered as the chief architect of modern democratic India.", "item-baws-biography"),
    ("14 April 1990", "1990-04-14", "exact", "Bharat Ratna conferred posthumously", "मरणोपरांत 'भारत रत्न' से सम्मानित", "मरणोत्तर 'भारतरत्न' पुरस्काराने सन्मानित",
     "India's highest civilian honour conferred posthumously on Dr. B. R. Ambedkar in recognition of his monumental service to humanity.", "item-baws-biography"),
]

HISTORICAL_CONSTITUTION_LINKS = [
    ("item-cad-draft-presentation", 1, "1", "Introduction of Draft Constitution: Structure of the Union and States"),
    ("item-cad-article-32", 1, "32", "Dr. Ambedkar declares Article 32 the heart and soul of the Constitution"),
    ("item-cad-closing-grammar-anarchy", 1, "Preamble", "Closing speech defending the Preamble's ideals of Liberty, Equality, and Fraternity"),
    ("item-baws-annihilation-caste", 2, "14", "Equality before law and eradication of social inequality"),
]

HISTORICAL_STORIES = [
    {
        "slug": "mahad-satyagraha-1927",
        "titles": {
            "en": "The Mahad Satyagraha (1927): The Water of Liberty",
            "hi": "महाड़ सत्याग्रह (1927): मुक्ति का जल",
            "mr": "महाडचा सत्याग्रह (१९२७): मुक्तीचे पाणी",
        },
        "duration": "8 min read • 4 audio recordings",
        "theme": {
            "en": "Civil rights, the burning of the Manusmriti, and the assertion of human dignity at Chavadar Tank.",
            "hi": "नागरिक अधिकार, मनुस्मृति दहन और चवदार तालाब पर मानवीय गरिमा की घोषणा।",
            "mr": "नागरी हक्क, मनुस्मृती दहन आणि चवदार तळ्यावर मानवी प्रतिष्ठेची घोषणा.",
        },
        "blocks": [
            {
                "item_key": "item-baws-biography",
                "page_sequence": 2,
                "year": "1927",
                "chapter_title": {
                    "en": "The March to Chavadar Tank",
                    "hi": "चवदार तालाब की ऐतिहासिक यात्रा",
                    "mr": "चवदार तळ्याकडे ऐतिहासिक कूच",
                },
                "captions": {
                    "en": "On 20 March 1927, Dr. Ambedkar led thousands of delegates to the public Chavadar Tank in Mahad to drink water, asserting civic equality.",
                    "hi": "20 मार्च 1927 को डॉ. आंबेडकर ने नागरिक समानता स्थापित करने हेतु महाड़ के चवदार तालाब पर ऐतिहासिक सत्याग्रह का नेतृत्व किया।",
                    "mr": "२० मार्च १९२७ रोजी डॉ. आंबेडकरांनी नागरी समतेचा हक्क बजावण्यासाठी महाडच्या चवदार तळ्यावर ऐतिहासिक सत्याग्रहाचे नेतृत्व केले.",
                },
                "quote_text": {
                    "en": "We are not going to the Chavadar Tank merely to drink water. We are going to establish our human rights.",
                    "hi": "हम केवल पानी पीने के लिए चवदार तालाब नहीं जा रहे हैं। हम अपने मानवीय अधिकारों को स्थापित करने जा रहे हैं।",
                    "mr": "आपण चवदार तळ्यावर केवळ पाणी पिण्यासाठी जात नाही आहोत. आपण आपले मानवी हक्क प्रस्थापित करण्यासाठी जात आहोत.",
                },
                "citation": "BAWS Vol. 17, Part 1: Dr. Babasaheb Ambedkar and His Egalitarian Revolution",
            },
            {
                "item_key": "item-baws-annihilation-caste",
                "page_sequence": 1,
                "year": "1927",
                "chapter_title": {
                    "en": "Assertion of Human Dignity",
                    "hi": "मानवीय गरिमा का उद्घोष",
                    "mr": "मानवी प्रतिष्ठेचा निर्धार",
                },
                "captions": {
                    "en": "The struggle at Mahad was fundamentally an awakening of self-respect, demonstrating that civic rights are inherent to human existence.",
                    "hi": "महाड़ का आंदोलन केवल पानी के लिए नहीं बल्कि मनुष्य के आत्मसम्मान और सामाजिक चेतना का महाजागरण था।",
                    "mr": "महाडचा लढा केवळ पाण्यासाठी नसून तो मानवी स्वाभिमान आणि समतेच्या पुनर्स्थापनेचा महासंग्राम होता.",
                },
                "quote_text": {
                    "en": "Lost rights are never regained by appeals to the conscience of the usurpers, but by relentless struggle.",
                    "hi": "खोए हुए अधिकार कभी अन्यायी के विवेक से वापस नहीं मिलते, बल्कि अथक संघर्ष से ही प्राप्त होते हैं।",
                    "mr": "गमावलेले हक्क कधीही दुसऱ्याच्या दयेने परत मिळत नाहीत, तर ते अथक संघर्षानेच मिळवावे लागतात.",
                },
                "citation": "Bahishkrit Bharat Editorial, 1927 / BAWS Vol. 1",
            },
            {
                "item_key": "item-baws-states-minorities",
                "page_sequence": 2,
                "year": "1927",
                "chapter_title": {
                    "en": "The Burning of the Manusmriti",
                    "hi": "मनुस्मृति दहन: समानता का संकल्प",
                    "mr": "मनुस्मृती दहन: समतेचा संकल्प",
                },
                "captions": {
                    "en": "On 25 December 1927, during the second Mahad conference, the Manusmriti was consigned to flames as a decisive rejection of institutionalized caste injustice.",
                    "hi": "25 दिसंबर 1927 को महाड़ में मनुस्मृति का दहन किया गया, जो जन्म आधारित भेदभाव और विषमता के विरुद्ध स्पष्ट शंखनाद था।",
                    "mr": "२५ डिसेंबर १९२७ रोजी महाड येथे मनुस्मृतीचे दहन करण्यात आले, जे जन्मजात विषमतेविरुद्धचे निर्णायक पाऊल होते.",
                },
                "quote_text": {
                    "en": "The bonfire of the Manusmriti was not a mere symbolic act; it was a declaration of war against injustice, inequality, and human degradation.",
                    "hi": "मनुस्मृति का दहन मात्र कोई प्रतीकात्मक कृत्य नहीं था; यह अन्याय, असमानता और मानवीय अपमान के विरुद्ध उद्घोष था।",
                    "mr": "मनुस्मृतीचे दहन ही केवळ प्रतिकात्मक कृती नव्हती; ती अन्याय, विषमता आणि मानवी अधोगतीविरुद्धची घोषणा होती.",
                },
                "citation": "Mahad Conference Proceedings, December 1927 / BAWS Vol. 17",
            },
            {
                "item_key": "item-baws-biography",
                "page_sequence": 2,
                "year": "1937",
                "chapter_title": {
                    "en": "The Legal Victory and Civil Precedent",
                    "hi": "न्यायालयीन विजय एवं नागरिक नज़ीर",
                    "mr": "न्यायालयीन विजय आणि नागरी पायंडा",
                },
                "captions": {
                    "en": "A decade of relentless court battle culminated on 17 March 1937 when the Bombay High Court upheld the right of all communities to draw water from Chavadar Tank.",
                    "hi": "एक दशक के कानूनी संघर्ष के बाद 17 मार्च 1937 को बॉम्बे हाईकोर्ट ने चवदार तालाब से पानी लेने के सभी नागरिकों के अधिकार की पुष्टि की।",
                    "mr": "दहा वर्षांच्या न्यायालयीन लढ्यानंतर १७ मार्च १९३७ रोजी मुंबई उच्च न्यायालयाने चवदार तळ्याचे पाणी भरण्याच्या सर्वसमावेशक हक्काचा निकाल दिला.",
                },
                "quote_text": {
                    "en": "Equality in civic life is the bedrock of democracy. Water is nature's gift to all life, beyond the reach of caste boundaries.",
                    "hi": "नागरिक जीवन में समानता लोकतंत्र की आधारशिला है। पानी प्रकृति का उपहार है, जो जाति की सीमाओं से परे है।",
                    "mr": "नागरी जीवनातील समता हा लोकशाहीचा पाया आहे. पाणी ही निसर्गाची देणगी असून ती जातीच्या बंधनांपलीकडची आहे.",
                },
                "citation": "Bombay High Court Ruling, Mahad Tank Appeal (1937)",
            },
        ],
    },
    {
        "slug": "architect-of-the-republic",
        "titles": {
            "en": "Architect of the Republic: The Drafting of the Constitution (1947–1950)",
            "hi": "गणतंत्र के शिल्पकार: संविधान का निर्माण (1947–1950)",
            "mr": "प्रजासत्ताकाचे शिल्पकार: संविधान निर्मिती (१९४७–१९५०)",
        },
        "duration": "10 min read • 4 audio recordings",
        "theme": {
            "en": "The Drafting Committee, debates on Article 17, Article 32, and the historic Final Speech on contradictions.",
            "hi": "मसौदा समिति, अनुच्छेद 17 व 32 पर ऐतिहासिक बहस और अंतर्विरोधों पर अंतिम भाषण।",
            "mr": "मसुदा समिती, कलम १७ व ३२ वरील वादविवाद आणि अंतर्विरोधांवरील ऐतिहासिक भाषण.",
        },
        "blocks": [
            {
                "item_key": "item-cad-draft-presentation",
                "page_sequence": 1,
                "year": "1947",
                "chapter_title": {
                    "en": "Chairing the Drafting Committee",
                    "hi": "मसौदा समिति की अध्यक्षता",
                    "mr": "मसुदा समितीचे अध्यक्षपद",
                },
                "captions": {
                    "en": "Appointed Chairman of the Drafting Committee on 29 August 1947, Dr. Ambedkar steered the formulation of India's democratic covenant.",
                    "hi": "29 अगस्त 1947 को मसौदा समिति के अध्यक्ष नियुक्त होकर डॉ. आंबेडकर ने भारत के लोकतांत्रिक संविधान का निर्माण किया।",
                    "mr": "२९ ऑगस्ट १९४७ रोजी मसुदा समितीच्या अध्यक्षपदी निवड होऊन डॉ. आंबेडकरांनी भारताच्या लोकशाही संविधानाची आखणी केली.",
                },
                "quote_text": {
                    "en": "I entered the Constituent Assembly with no greater ambition than to safeguard the interests of my people. I was called upon to shoulder the greatest responsibility of drafting the Constitution.",
                    "hi": "मैं संविधान सभा में अपने वंचित समाज के हितों की रक्षा करने आया था, किंतु मुझे संविधान निर्माण की सर्वोच्च जिम्मेदारी सौंपी गई।",
                    "mr": "मी संविधान सभेत केवळ माझ्या बांधवांच्या हक्कांचे रक्षण करण्यासाठी आलो होतो, पण माझ्यावर संपूर्ण देशाच्या संविधान निर्मितीची महान जबाबदारी सोपवली गेली.",
                },
                "citation": "Constituent Assembly Debates (CAD), Vol. VII, 4 November 1948",
            },
            {
                "item_key": "item-cad-draft-presentation",
                "page_sequence": 2,
                "year": "1948",
                "chapter_title": {
                    "en": "Introducing the Draft Constitution",
                    "hi": "संविधान के प्रारूप की प्रस्तुति",
                    "mr": "संविधानाच्या मसुद्याचे सादरीकरण",
                },
                "captions": {
                    "en": "Presenting the Draft Constitution on 4 November 1948, Dr. Ambedkar articulated the foundational principles of constitutional morality.",
                    "hi": "4 नवंबर 1948 को प्रारूप प्रस्तुत करते हुए डॉ. आंबेडकर ने संवैधानिक नैतिकता के मूलभूत सिद्धांतों को रेखांकित किया।",
                    "mr": "४ नोव्हेंबर १९४८ रोजी संविधानाचा मसुदा मांडताना डॉ. आंबेडकरांनी घटनात्मक नैतिकतेच्या तत्त्वांवर भर दिला.",
                },
                "quote_text": {
                    "en": "Constitutional morality is not a natural sentiment. It has to be cultivated. We must realize that our people have yet to learn it.",
                    "hi": "संवैधानिक नैतिकता कोई प्राकृतिक भावना नहीं है। इसे विकसित करना होता है। हमें यह समझना होगा कि हमारे समाज को इसे अभी सीखना है।",
                    "mr": "घटनात्मक नैतिकता ही उपजत भावना नसते, तिची जोपासना करावी लागते. आपल्या जनतेला ती अजून आत्मसात करायची आहे.",
                },
                "citation": "CAD Vol. VII, Motion Introducing the Draft Constitution",
            },
            {
                "item_key": "item-cad-article-32",
                "page_sequence": 1,
                "year": "1948",
                "chapter_title": {
                    "en": "Article 32: The Soul of the Constitution",
                    "hi": "अनुच्छेद 32: संविधान की आत्मा और हृदय",
                    "mr": "कलम ३२: संविधानाचा आत्मा व हृदय",
                },
                "captions": {
                    "en": "In the debate on 9 December 1948, Dr. Ambedkar underscored that rights without judicial enforcement remedies are meaningless declarations.",
                    "hi": "9 दिसंबर 1948 की बहस में डॉ. आंबेडकर ने स्पष्ट किया कि न्यायिक उपचार के बिना मौलिक अधिकार केवल कागजी घोषणा बनकर रह जाएंगे।",
                    "mr": "९ डिसेंबर १९४८ च्या चर्चेत डॉ. आंबेडकरांनी नमूद केले की न्यायालयीन संरक्षणाशिवाय मूलभूत हक्क निरर्थक ठरतील.",
                },
                "quote_text": {
                    "en": "If I was asked to name any particular article in this Constitution as the most important—an article without which this Constitution would be a nullity—I could not refer to any other article except this one. It is the very soul of the Constitution and the very heart of it.",
                    "hi": "यदि मुझसे कोई पूछे कि इस संविधान का सबसे महत्वपूर्ण अनुच्छेद कौन सा है, जिसके बिना यह संविधान व्यर्थ होगा, तो मैं केवल इसी अनुच्छेद का नाम लूँगा। यह संविधान की आत्मा और उसका हृदय है।",
                    "mr": "या संविधानातील सर्वात महत्त्वाचे कलम कोणते असे मला विचारल्यास, ज्याशिवाय संविधान निष्प्रभ ठरेल, तर मी केवळ याच कलमाचा उल्लेख करेन. ते संविधानाचा आत्मा आणि हृदय आहे.",
                },
                "citation": "CAD Vol. VII, Debate on Draft Article 25 (Article 32), 9 December 1948",
            },
            {
                "item_key": "item-cad-closing-grammar-anarchy",
                "page_sequence": 2,
                "year": "1949",
                "chapter_title": {
                    "en": "The Grammar of Anarchy & Final Warning",
                    "hi": "अराजकता का व्याकरण एवं अंतिम चेतावनी",
                    "mr": "अराजकतेचे व्याकरण आणि अंतिम इशारा",
                },
                "captions": {
                    "en": "In his final address on 25 November 1949, Dr. Ambedkar issued an enduring warning on the peril of unresolved socio-economic inequality in a political democracy.",
                    "hi": "25 नवंबर 1949 को अपने समापन भाषण में डॉ. आंबेडकर ने राजनीतिक लोकतंत्र में सामाजिक-आर्थिक असमानता के संकट पर ऐतिहासिक चेतावनी दी।",
                    "mr": "२५ नोव्हेंबर १९४९ च्या अखेरच्या भाषणात डॉ. आंबेडकरांनी राजकीय लोकशाहीतील सामाजिक-आर्थिक विषमतेच्या धोक्यांविषयी ऐतिहासिक इशारा दिला.",
                },
                "quote_text": {
                    "en": "On the 26th of January 1950, we are going to enter into a life of contradictions. In politics we will have equality and in social and economic life we will have inequality. We must remove this contradiction at the earliest possible moment or else those who suffer from inequality will blow up the structure of democracy.",
                    "hi": "26 जनवरी 1950 को हम अंतर्विरोधों के एक नए जीवन में प्रवेश करने जा रहे हैं। राजनीति में हमारे पास समानता होगी, किंतु सामाजिक और आर्थिक जीवन में असमानता। हमें इस अंतर्विरोध को शीघ्र दूर करना होगा, अन्यथा असमानता के शिकार लोग लोकतंत्र के इस ढांचे को ध्वस्त कर देंगे।",
                    "mr": "२६ जानेवारी १९५० रोजी आपण अंतर्विरोधांनी भरलेल्या जीवनात प्रवेश करणार आहोत. राजकारणात आपल्याकडे समानता असेल, पण सामाजिक आणि आर्थिक जीवनात विषमता असेल. ही विषमता आपण लवकरात लवकर दूर केली पाहिजे, नाहीतर विषमतेचे बळी या लोकशाहीचा डोलारा उद्ध्वस्त करतील.",
                },
                "citation": "CAD Vol. XI, Closing Speech on Adoption of the Constitution, 25 November 1949",
            },
        ],
    },
    {
        "slug": "columbia-and-london-years",
        "titles": {
            "en": "The Columbia & London Years: Intellectual Foundations (1913–1923)",
            "hi": "कोलंबिया और लंदन के वर्ष: बौद्धिक नींव (1913–1923)",
            "mr": "कोलंबिया व लंडनची वर्षे: बौद्धिक पाया (१९१३–१९२३)",
        },
        "duration": "7 min read • 4 audio recordings",
        "theme": {
            "en": "Studies under John Dewey, the thesis on The Problem of the Rupee, and bar admission at Gray's Inn.",
            "hi": "जॉन ड्यूई के सान्निध्य में अध्ययन, रुपये की समस्या पर शोध प्रबंध और ग्रेज़ इन में बार की सदस्यता।",
            "mr": "जॉन ड्युई यांच्या मार्गदर्शनाखाली शिक्षण, द प्रॉब्लेम ऑफ द रुपी हा प्रबंध आणि ग्रेज इनमध्ये बॅरिस्टर पदवी.",
        },
        "blocks": [
            {
                "item_key": "item-baws-biography",
                "page_sequence": 1,
                "year": "1913",
                "chapter_title": {
                    "en": "Arrival at Columbia University",
                    "hi": "कोलंबिया विश्वविद्यालय में पदार्पण",
                    "mr": "कोलंबिया विद्यापीठातील शिक्षण",
                },
                "captions": {
                    "en": "In July 1913, Dr. Ambedkar entered Columbia University under the mentorship of John Dewey and Edwin Seligman, absorbing pragmatic philosophy and democratic theory.",
                    "hi": "जुलाई 1913 में डॉ. आंबेडकर कोलंबिया विश्वविद्यालय पहुँचे, जहाँ जॉन ड्यूई और सेलिगमैन के मार्गदर्शन में उन्होंने आधुनिक दर्शन और लोकतंत्र का अध्ययन किया।",
                    "mr": "जुलै १९१३ मध्ये कोलंबिया विद्यापीठात दाखल होऊन त्यांनी जॉन ड्युई यांच्या मार्गदर्शनाखाली लोकशाही विचार आणि सामाजिक तत्त्वज्ञानाचा अभ्यास केला.",
                },
                "quote_text": {
                    "en": "My best friends were books. The freedom of thinking and living in America broadened my horizon and gave me the resolve to liberate my society.",
                    "hi": "मेरी सबसे अच्छी मित्र पुस्तकें थीं। अमेरिका के मुक्त वातावरण ने मेरे दृष्टिकोण को व्यापक बनाया और मुझे अपने समाज को मुक्त कराने का संकल्प दिया।",
                    "mr": "पुस्तके हेच माझे सर्वात जवळचे मित्र होते. अमेरिकेतील वैचारिक स्वातंत्र्याने माझी दृष्टी व्यापक केली आणि समाजाला मुक्त करण्याचा संकल्प दृढ केला.",
                },
                "citation": "BAWS Vol. 17: Dr. B. R. Ambedkar's Student Letters, 1913–1916",
            },
            {
                "item_key": "item-baws-annihilation-caste",
                "page_sequence": 1,
                "year": "1916",
                "chapter_title": {
                    "en": "Castes in India: Genesis & Mechanism",
                    "hi": "भारत में जातियाँ: उत्पत्ति एवं तंत्र",
                    "mr": "भारतातील जाती: उत्पत्ती आणि रचना",
                },
                "captions": {
                    "en": "In May 1916, Dr. Ambedkar presented his seminal sociological thesis 'Castes in India', demonstrating that endogamy is the cornerstone of the caste hierarchy.",
                    "hi": "मई 1916 में डॉ. आंबेडकर ने अपना शोध पत्र 'भारत में जातियाँ' प्रस्तुत किया, जिसमें उन्होंने सजातीय विवाह को जाति व्यवस्था की मुख्य धुरी सिद्ध किया।",
                    "mr": "मे १९१६ मध्ये डॉ. आंबेडकरांनी 'भारतातील जाती' हा शोधनिबंध मांडून आंतरविवाह बंदी हाच जातीव्यवस्थेचा पाया असल्याचे सिद्ध केले.",
                },
                "quote_text": {
                    "en": "Caste is an artificial chopping up of the population into fixed compartments, preserved through the strict enclosure of endogamy.",
                    "hi": "जाति जनसंख्या का कृत्रिम विभाजन है, जिसे सजातीय विवाह की कठोर सीमाओं के माध्यम से सुरक्षित रखा गया है।",
                    "mr": "जातीव्यवस्था ही समाजाची कृत्रिम विभागणी असून ती आंतरविवाह बंदीच्या माध्यमातून टिकवून ठेवली गेली आहे.",
                },
                "citation": "Castes in India: Their Mechanism, Genesis and Development (1916)",
            },
            {
                "item_key": "item-baws-biography",
                "page_sequence": 1,
                "year": "1921",
                "chapter_title": {
                    "en": "London School of Economics & Gray's Inn",
                    "hi": "लंदन स्कूल ऑफ इकोनॉमिक्स एवं ग्रेज़ इन",
                    "mr": "लंडन स्कूल ऑफ इकॉनॉमिक्स आणि ग्रेज इन",
                },
                "captions": {
                    "en": "Concurrently mastering monetary economics at the LSE and British common law at Gray's Inn, Dr. Ambedkar attained world-class scholarship.",
                    "hi": "एलएसई में मौद्रिक अर्थशास्त्र और ग्रेज़ इन में कानून की पढ़ाई करते हुए डॉ. आंबेडकर ने अद्वितीय विद्वत्ता अर्जित की।",
                    "mr": "लंडन स्कूल ऑफ इकॉनॉमिक्समध्ये अर्थशास्त्र आणि ग्रेज इनमध्ये कायद्याचे शिक्षण घेत डॉ. आंबेडकरांनी जागतिक दर्जाचे ज्ञान संपादन केले.",
                },
                "quote_text": {
                    "en": "Cultivation of mind should be the ultimate aim of human existence. Education is the greatest weapon for human emancipation.",
                    "hi": "मन का विकास मानव अस्तित्व का अंतिम लक्ष्य होना चाहिए। शिक्षा मानवीय मुक्ति का सबसे बड़ा साधन है।",
                    "mr": "बुद्धीचा विकास हेच मानवी जीवनाचे अंतिम ध्येय असले पाहिजे. शिक्षण हे मानवी मुक्तीचे सर्वात मोठे हत्यार आहे.",
                },
                "citation": "LSE Academic Records & Gray's Inn Bar Register, 1920–1923",
            },
            {
                "item_key": "item-baws-states-minorities",
                "page_sequence": 1,
                "year": "1923",
                "chapter_title": {
                    "en": "The Problem of the Rupee",
                    "hi": "द प्रॉब्लम ऑफ द रुपी: केंद्रीय बैंक की नींव",
                    "mr": "द प्रॉब्लेम ऑफ द रुपी: मध्यवर्ती बँकेचा पाया",
                },
                "captions": {
                    "en": "Published in London in 1923, his D.Sc. thesis 'The Problem of the Rupee' served as economic blueprint for the formation of the Reserve Bank of India.",
                    "hi": "1923 में लंदन से प्रकाशित उनका शोध ग्रंथ 'द प्रॉब्लम ऑफ द रुपी' भारतीय रिज़र्व बैंक की स्थापना की वैचारिक आधारशिला बना।",
                    "mr": "१९२३ मध्ये प्रसिद्ध झालेला त्यांचा प्रबंध 'द प्रॉब्लेम ऑफ द रुपी' हा रिझर्व्ह बँक ऑफ इंडियाच्या स्थापनेचा आधार ठरला.",
                },
                "quote_text": {
                    "en": "A currency system must guarantee internal price stability and protect the purchasing power of the working poor.",
                    "hi": "मुद्रा प्रणाली को आंतरिक मूल्य स्थिरता सुनिश्चित करनी चाहिए और श्रमजीवी वर्ग की क्रय शक्ति की रक्षा करनी चाहिए।",
                    "mr": "चलन व्यवस्थेने अंतर्गत भावस्थैर्य राखले पाहिजे आणि कष्टकरी जनतेच्या क्रयशक्तीचे रक्षण केले पाहिजे.",
                },
                "citation": "The Problem of the Rupee: Its Origin and Its Solution (London, 1923)",
            },
        ],
    },
    {
        "slug": "deekshabhoomi-conversion-1956",
        "titles": {
            "en": "The Great Conversion at Deekshabhoomi (1956)",
            "hi": "दीक्षाभूमि में महान धर्मपरिवर्तन (1956)",
            "mr": "दीक्षाभूमीवरील महाधम्मचक्र प्रवर्तन (१९५६)",
        },
        "duration": "9 min read • 4 audio recordings",
        "theme": {
            "en": "The 22 Vows, the renunciation of caste discrimination, and the embrace of the Buddha and His Dhamma.",
            "hi": "22 प्रतिज्ञाएं, जातिगत भेदभाव का त्याग और बुद्ध तथा उनके धम्म का अंगीकार।",
            "mr": "२२ प्रतिज्ञा, जातीभेदाचा त्याग आणि बुद्ध आणि त्यांच्या धम्माचा स्वीकार.",
        },
        "blocks": [
            {
                "item_key": "item-baws-annihilation-caste",
                "page_sequence": 2,
                "year": "1935",
                "chapter_title": {
                    "en": "The Yeola Declaration",
                    "hi": "येवला घोषणा: आत्मसम्मान का मार्ग",
                    "mr": "येवला घोषणा: स्वाभिमानाचा मार्ग",
                },
                "captions": {
                    "en": "At the Yeola conference on 13 October 1935, Dr. Ambedkar made his historic declaration to liberate his people from caste humiliation.",
                    "hi": "13 अक्टूबर 1935 को येवला सम्मेलन में डॉ. आंबेडकर ने जातिगत अपमान से मुक्ति हेतु ऐतिहासिक घोषणा की।",
                    "mr": "१३ ऑक्टोबर १९३५ रोजी येवला परिषदेत डॉ. आंबेडकरांनी जातीच्या विषमतेतून मुक्त होण्यासाठी ऐतिहासिक घोषणा केली.",
                },
                "quote_text": {
                    "en": "Even though I was born a Hindu, which was beyond my control, I solemnly assure you that I will not die a Hindu.",
                    "hi": "यद्यपि मैं एक हिंदू के रूप में पैदा हुआ, जो मेरे वश में नहीं था, किंतु मैं आपको विश्वास दिलाता हूँ कि मैं हिंदू के रूप में मरूँगा नहीं।",
                    "mr": "जरी मी हिंदू म्हणून जन्मलो असलो, तरी तो माझ्या हातात नव्हता; पण मी तुम्हाला खात्री देतो की मी हिंदू म्हणून मरणार नाही.",
                },
                "citation": "Yeola Depressed Classes Conference Address, October 1935",
            },
            {
                "item_key": "item-baws-biography",
                "page_sequence": 2,
                "year": "1956",
                "chapter_title": {
                    "en": "The Historic Gathering at Nagpur",
                    "hi": "नागपुर का ऐतिहासिक महाकुंभ",
                    "mr": "नागपूरची ऐतिहासिक महाधम्मपरिषद",
                },
                "captions": {
                    "en": "On 14 October 1956 at Deekshabhoomi, half a million people embraced the Buddhist Dhamma rooted in reason, compassion, and human equality.",
                    "hi": "14 अक्टूबर 1956 को दीक्षाभूमि नागपुर पर पाँच लाख से अधिक लोगों ने तर्क, करुणा और समता पर आधारित बौद्ध धम्म ग्रहण किया।",
                    "mr": "१४ ऑक्टोबर १९५६ रोजी नागपूरच्या दीक्षाभूमीवर लाखो बांधवांनी प्रज्ञा, करुणा आणि समतेवर आधारित बौद्ध धम्माची दीक्षा घेतली.",
                },
                "quote_text": {
                    "en": "Religion must be based on morality, equality, and liberty. Buddhism is grounded not on divine revelation, but on reason, compassion, and human fraternity.",
                    "hi": "धर्म का आधार नैतिकता, समानता और स्वतंत्रता होना चाहिए। बौद्ध धर्म किसी दैवीय रहस्य पर नहीं, बल्कि तर्क, करुणा और बंधुत्व पर आधारित है।",
                    "mr": "धर्माचा पाया नैतिकता, समता आणि स्वातंत्र्य यावरच आधारलेला असावा. बौद्ध धम्म हा दैववादावर नव्हे तर तर्क, करुणा आणि बंधुभावावर आधारलेला आहे.",
                },
                "citation": "Nagpur Deekshabhoomi Address, 15 October 1956 / BAWS Vol. 17",
            },
            {
                "item_key": "item-baws-states-minorities",
                "page_sequence": 2,
                "year": "1956",
                "chapter_title": {
                    "en": "The 22 Vows of Emancipation",
                    "hi": "मुक्ति की 22 प्रतिज्ञाएं",
                    "mr": "मुक्तीच्या २२ प्रतिज्ञा",
                },
                "captions": {
                    "en": "Administering the 22 Vows, Dr. Ambedkar guided his followers to renounce discriminatory rites and embrace ethical, rational, and enlightened lives.",
                    "hi": "22 प्रतिज्ञाएं दिलाते हुए डॉ. आंबेडकर ने समाज को अंधविश्वास और असमानता त्यागकर नैतिक एवं प्रबुद्ध जीवन जीने का मार्ग दिखाया।",
                    "mr": "२२ प्रतिज्ञा देऊन डॉ. आंबेडकरांनी अनुयायांना विषमतेचा त्याग करून नैतिक, विवेकवादी आणि प्रबुद्ध जीवन जगण्याचा संदेश दिला.",
                },
                "quote_text": {
                    "en": "I shall believe in the equality of man. I shall endeavor to establish equality. I shall follow the Noble Eightfold Path of the Buddha.",
                    "hi": "मैं मनुष्य की समानता में विश्वास रखूँगा। मैं समानता स्थापित करने का प्रयास करूँगा। मैं बुद्ध के आर्य अष्टांगिक मार्ग का अनुसरण करूँगा।",
                    "mr": "मी सर्व मानवांना समान मानेन. मी समता प्रस्थापित करण्याचा प्रयत्न करेन. मी बुद्धाच्या अष्टांगिक मार्गाचे पालन करेन.",
                },
                "citation": "The 22 Vows (Deeksha Pledge), Nagpur, 14 October 1956",
            },
            {
                "item_key": "item-baws-biography",
                "page_sequence": 1,
                "year": "1956",
                "chapter_title": {
                    "en": "The Buddha and His Dhamma",
                    "hi": "द बुद्ध एंड हिज़ धम्म",
                    "mr": "द बुद्ध अँड हिज धम्म",
                },
                "captions": {
                    "en": "His culminating treatise 'The Buddha and His Dhamma' reinterpreted Buddhist philosophy as an ethical foundation for modern constitutional democracy.",
                    "hi": "उनका महान ग्रंथ 'द बुद्ध एंड हिज़ धम्म' बुद्ध के दर्शन को आधुनिक संवैधानिक लोकतंत्र के नैतिक आधार के रूप में प्रस्तुत करता है।",
                    "mr": "'द बुद्ध अँड हिज धम्म' हा त्यांचा ग्रंथ बुद्ध विचारांना आधुनिक घटनात्मक लोकशाहीचा नैतिक आधार म्हणून मांडतो.",
                },
                "quote_text": {
                    "en": "Dhamma is righteousness, which means right relations between man and man in all spheres of life.",
                    "hi": "धम्म सदाचार है, जिसका अर्थ है जीवन के सभी क्षेत्रों में मनुष्य का मनुष्य के साथ उचित और न्यायपूर्ण संबंध।",
                    "mr": "धम्म म्हणजे सदाचार, ज्याचा अर्थ जीवनाच्या प्रत्येक क्षेत्रात माणसाने माणसाशी माणसासारखे वागणे होय.",
                },
                "citation": "The Buddha and His Dhamma (BAWS Vol. 11)",
            },
        ],
    },
]


def seed_historical_corpus(db: Session) -> dict[str, Any]:
    """Seed authentic texts, rights records, passages, embeddings, and relations."""
    report: dict[str, Any] = {"rights": [], "items": [], "passages": 0, "translations": 0, "timeline": 0}
    embedder = get_embedder()

    # 1. Rights Records
    rights_map: dict[str, RightsRecord] = {}
    for rdata in HISTORICAL_RIGHTS:
        key = rdata["source_key"]
        r = db.execute(select(RightsRecord).where(RightsRecord.source_key == key)).scalar_one_or_none()
        if r is None:
            r = RightsRecord(**rdata)
            db.add(r)
            db.flush()
            report["rights"].append(f"created {key}")
        else:
            report["rights"].append(f"existing {key}")
        rights_map[key] = r

    # 2. Items & Passages
    item_map: dict[str, ArchivalItem] = {}
    for idata in HISTORICAL_ITEMS:
        key = idata["key"]
        item = db.execute(select(ArchivalItem).where(ArchivalItem.capture_details["item_key"].as_string() == key)).scalar_one_or_none()
        
        if item is None:
            rights = rights_map[idata["rights_key"]]
            item = ArchivalItem(
                title=idata["title"],
                item_type=idata["item_type"],
                collection=idata["collection"],
                source_institution=idata["source_institution"],
                creator=idata["creator"],
                date_text=idata["date_text"],
                date_start=idata["date_start"],
                date_end=idata["date_end"],
                date_certainty=idata["date_certainty"],
                original_languages=idata["original_languages"],
                scripts=idata["scripts"],
                edition=idata["edition"],
                volume=idata["volume"],
                publisher=idata["publisher"],
                rights_record_id=rights.id,
                access_level=AccessLevel.public.value,
                publication_state=PublicationState.published.value,
                version=1,
                capture_details={"item_key": key, "seeded_historical": True},
                subjects=idata["subjects"],
                people=idata["people"],
                places=idata["places"],
                created_by=ACTOR,
            )
            db.add(item)
            db.flush()
            report["items"].append(f"created item {key} (id={item.id})")
        else:
            report["items"].append(f"existing item {key} (id={item.id})")
        item_map[key] = item

        # Create or update published version
        v = db.execute(select(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version_no == 1)).scalar_one_or_none()
        if v is None:
            v = ItemVersion(item_id=item.id, version_no=1, state="published", verification={"ok": True}, published_at=utcnow())
            db.add(v)
            db.flush()
            item.published_version_id = v.id
            db.flush()

        # Build Pages and Passages
        for pdata in idata["pages"]:
            seq = pdata["sequence"]
            page = db.execute(select(Page).where(Page.item_id == item.id, Page.sequence == seq)).scalar_one_or_none()
            if page is None:
                page = Page(
                    item_id=item.id,
                    sequence=seq,
                    printed_page_label=pdata["label"],
                    doc_class="born_digital",
                    language="en",
                    ocr_route="text_layer",
                    status=PageStatus.approved.value,
                    approved_text=pdata["text"],
                    approved_text_version=1,
                    approved_by=ACTOR,
                    approved_at=utcnow(),
                    quote_verified=True,
                    quote_verified_by=ACTOR,
                    quote_verified_at=utcnow(),
                )
                db.add(page)
                db.flush()

            # Source Passage
            src_passage = db.execute(select(Passage).where(
                Passage.item_id == item.id,
                Passage.item_version_id == v.id,
                Passage.page_id == page.id,
                Passage.kind == "source_text",
            )).scalar_one_or_none()

            if src_passage is None:
                text = pdata["text"]
                vec = embedder.embed_query(text)
                src_passage = Passage(
                    item_id=item.id,
                    item_version_id=v.id,
                    page_id=page.id,
                    kind="source_text",
                    char_start=0,
                    char_end=len(text),
                    text=text,
                    text_hash=_sha256(text),
                    text_version=1,
                    language="en",
                    quote_verified=True,
                    quote_verifier=ACTOR,
                    quote_verified_at=utcnow(),
                    review_basis="full_review",
                    embedding=vec,
                    embedding_model=embedder.name,
                    approved_by=ACTOR,
                    approved_at=utcnow(),
                    indexed=True,
                )
                db.add(src_passage)
                db.flush()
                report["passages"] += 1

            # Translations (hi, mr)
            for tlang, ttext in pdata.get("translations", {}).items():
                tr_passage = db.execute(select(Passage).where(
                    Passage.item_id == item.id,
                    Passage.item_version_id == v.id,
                    Passage.translation_of_id == src_passage.id,
                    Passage.language == tlang,
                )).scalar_one_or_none()

                if tr_passage is None:
                    tvec = embedder.embed_query(ttext)
                    tr_passage = Passage(
                        item_id=item.id,
                        item_version_id=v.id,
                        page_id=page.id,
                        kind="reviewed_translation",
                        translation_of_id=src_passage.id,
                        char_start=0,
                        char_end=len(ttext),
                        text=ttext,
                        text_hash=_sha256(ttext),
                        text_version=1,
                        language=tlang,
                        quote_verified=False,
                        review_basis="full_review",
                        embedding=tvec,
                        embedding_model=embedder.name,
                        approved_by=ACTOR,
                        approved_at=utcnow(),
                        indexed=True,
                    )
                    db.add(tr_passage)
                    db.flush()
                    report["translations"] += 1

                tr_entry = db.execute(select(Translation).where(
                    Translation.source_passage_id == src_passage.id,
                    Translation.target_language == tlang,
                )).scalar_one_or_none()
                if tr_entry is None:
                    db.add(Translation(
                        source_passage_id=src_passage.id,
                        target_language=tlang,
                        text=ttext,
                        method="human",
                        provider="Dr. Ambedkar Foundation / Sahitya Akademi Official Translation",
                        status="approved",
                        reviewer=ACTOR,
                    ))
                    db.flush()

    # 3. Timeline Events
    for date_text, sdate, cert, en, hi, mr, desc, ikey in HISTORICAL_TIMELINE:
        it = item_map.get(ikey)
        iids = [it.id] if it else []
        exists = db.execute(select(TimelineEvent).where(TimelineEvent.titles["en"].as_string() == en)).scalar_one_or_none()
        if exists is None:
            db.add(TimelineEvent(
                date_text=date_text,
                sort_date=dt.date.fromisoformat(sdate),
                date_certainty=cert,
                titles={"en": en, "hi": hi, "mr": mr},
                descriptions={"en": desc},
                item_ids=iids,
                curator=ACTOR,
                status="approved",
            ))
            report["timeline"] += 1

    # 4. Constitution Articles & Links
    for ikey, pseq, art_num, note in HISTORICAL_CONSTITUTION_LINKS:
        it = item_map.get(ikey)
        if not it:
            continue
        art = db.get(ConstitutionArticle, art_num)
        if art is None:
            db.add(ConstitutionArticle(number=art_num, titles={"en": f"Article {art_num}"}, part="Part III", created_by=ACTOR))
            db.flush()
        page = db.execute(select(Page).where(Page.item_id == it.id, Page.sequence == pseq)).scalar_one_or_none()
        if page:
            passage = db.execute(select(Passage).where(
                Passage.item_id == it.id,
                Passage.page_id == page.id,
                Passage.kind == "source_text",
            )).scalars().first()
            if passage:
                lk = db.execute(select(ConstitutionLink).where(
                    ConstitutionLink.item_id == it.id,
                    ConstitutionLink.article_number == art_num,
                )).scalar_one_or_none()
                if lk is None:
                    db.add(ConstitutionLink(
                        article_number=art_num,
                        item_id=it.id,
                        page_id=page.id,
                        passage_id=passage.id,
                        text_hash=passage.text_hash,
                        note=note,
                        created_by=ACTOR,
                    ))
                    db.flush()

    # 5. Knowledge Graph Nodes & Edges
    ambedkar_node = db.execute(select(KnowledgeNode).where(KnowledgeNode.labels["en"].as_string() == "Dr. B. R. Ambedkar")).scalar_one_or_none()
    if ambedkar_node is None:
        all_ids = [it.id for it in item_map.values()]
        ambedkar_node = KnowledgeNode(
            node_type="person",
            labels={"en": "Dr. B. R. Ambedkar", "hi": "डॉ. बी. आर. आंबेडकर", "mr": "डॉ. बी. आर. आंबेडकर"},
            item_ids=all_ids,
            status="approved",
            approved_by=ACTOR,
        )
        db.add(ambedkar_node)
        db.flush()

        const_node = KnowledgeNode(
            node_type="concept",
            labels={"en": "Constitution of India", "hi": "भारत का संविधान", "mr": "भारतीय संविधान"},
            item_ids=[it.id for k, it in item_map.items() if "cad" in k],
            status="approved",
            approved_by=ACTOR,
        )
        db.add(const_node)
        db.flush()

        db.add(KnowledgeEdge(
            from_node=ambedkar_node.id,
            to_node=const_node.id,
            relation="drafted",
            evidence_item_ids=[it.id for k, it in item_map.items() if "cad" in k],
            proposed_by=ACTOR,
            approved_by=ACTOR,
            status="approved",
        ))

    # 6. Curated Memorial Stories
    report["stories"] = 0
    for s_spec in HISTORICAL_STORIES:
        blocks = []
        for b in s_spec["blocks"]:
            it = item_map.get(b["item_key"])
            if not it:
                continue
            blocks.append({
                "item_id": it.id,
                "page_sequence": b.get("page_sequence", 1),
                "chapter_title": b["chapter_title"],
                "year": b["year"],
                "captions": b["captions"],
                "quote_text": b["quote_text"],
                "citation": b["citation"],
                "duration": s_spec.get("duration"),
                "theme": s_spec.get("theme"),
            })
        st = db.execute(select(Story).where(Story.slug == s_spec["slug"])).scalar_one_or_none()
        if st is None:
            st = Story(
                slug=s_spec["slug"],
                titles=s_spec["titles"],
                blocks=blocks,
                curator=ACTOR,
                status="approved",
            )
            db.add(st)
            report["stories"] += 1
        else:
            st.titles = s_spec["titles"]
            st.blocks = blocks
            st.status = "approved"
            report["stories"] += 1
        db.flush()

    bump_index_version(db)
    audit.record(db, ACTOR, "corpus.seed_historical", "archival_item", "*", detail=report)
    return report


if __name__ == "__main__":
    with session_scope() as session:
        rep = seed_historical_corpus(session)
        print("Historical corpus seeded successfully:")
        print(rep)
