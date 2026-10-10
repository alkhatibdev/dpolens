# Where this pack's text comes from

Federal Decree by Law No. (45) of 2021 Concerning the Protection of Personal Data, issued
20 September 2021, published in Official Gazette No. 712 (supplement) on 26 September 2021,
in force since 2 January 2022. The portal lists no amendment.

The Arabic text is the law. The English is the official translation published on the same
portal, which says that in case of conflict the Arabic text prevails. Both are free of
copyright under Federal Decree by Law No. (38) of 2021 on Copyright and Neighbouring Rights,
Article (3).

## How it was built

The United Arab Emirates Legislations portal publishes each law twice: as a web page and as a
PDF. Both versions of both languages were saved from it by hand:

| Language | Page | PDF SHA-256 |
| --- | --- | --- |
| Arabic | <https://uaelegislation.gov.ae/ar/legislations/1972> | `74a19403c31259f6b8c62e7a6e4fa6c5afaebd875071a83af269fed908a09dcd` |
| English | <https://uaelegislation.gov.ae/en/legislations/1972> | `d5d5f9e93bd6c0dc2afe79776f3101bcd599e4400a67309bc0b378b2812bcf3a` |

The text was taken from the web pages, because the Arabic PDF does not survive text
extraction: letters drawn joined come out reversed, and runs that mix Arabic with digits and
brackets come out reordered. The web pages hold the text in reading order. Both pages list
the same 31 articles, under the same identifiers, in the same order.

Every article was then compared with the PDF of the same language: the English word by word,
and the Arabic letter by letter, which reordering cannot change. Where they differed, the web
page was wrong in every case but one, and the pack takes the PDF's wording. After those
corrections, the English matches its PDF word for word and every Arabic article matches its
PDF except for spellings that change no word: hamza on or off an alef, ؤ and و, ة and ه, and
the stretching stroke. There the pack keeps the web page's spelling.

The clause keys follow the Arabic numbering, and the English text sits under the same keys.
The articles' own lettered points use the Arabic letters in order, أ, ب, ج, and so on, which
the keys write as `pt-a`, `pt-b`, `pt-c`.

## Where the pack departs from the web page

| Article | Language | Web page | Pack, as the PDF has it |
| --- | --- | --- | --- |
| 1, definition of automated processing | Arabic | المعالجة المؤتمنة | المعالجة المؤتمتة |
| 1, definition of profiling | Arabic | تعليل أو توقع | تحليل أو توقع |
| 2(1)(a) | Arabic | صاحب بيانات بقيم | صاحب بيانات يقيم |
| 4(4) | Arabic | رفقاً للتشريعات | وفقاً للتشريعات |
| 5(8) | Arabic | أية ضوابط أخرى | أي ضوابط أخرى |
| 6(1)(b) | Arabic | وغير مهمة | وغير مبهمة |
| 7 | Arabic | مراعاة طبية ونطاق | مراعاة طبيعة ونطاق |
| 8 | Arabic | على أن تراعى فيها | على أن يراعى فيها |
| 8 | Arabic | وفي حال تجاوز المعالجة | وفي حال تجاوزت المعالجة |
| 9 | Arabic | لحدوث الاختراق و الانتهاك | لحدوث الاختراق أو الانتهاك |
| 13 | Arabic | المعالجة المؤتمنة بما فيها | المعالجة المؤتمتة بما فيها |
| 20(1) | Arabic | أمن المعلومات التي يتناسب | أمن المعلومات الذي يتناسب |
| 20(2) | Arabic | المنصوص عليه في البند (1) | المنصوص عليها في البند (1) |
| 22(1) | Arabic | البيانات الشخصية إلها | البيانات الشخصية إليها |
| 22 | Arabic | الدول التي يتم نقل | الدول التي سيتم نقل |
| 23, title | Arabic | في حال وجود مستوى حماية ملائم | في حال عدم وجود مستوى حماية ملائم |
| 2(1)(a), label | English | 2. | a. |
| 11(1)(b) | English | Drcree-Law | Decree-Law |

Several of these change the meaning. On the web page, consent must be "غير مهمة"
(unimportant) rather than "غير مبهمة" (unambiguous), and article 23's title repeats article
22's, so it says the opposite of the law.

The one difference that runs the other way: the English PDF letters the first point of
article 11(1) "b." and then repeats "b.". The web page's "a." matches the Arabic "أ.", and the
pack keeps it.

## What has not been done

The pack is `community`: it has passed validation, and nobody qualified in UAE law has read it
against the official text. That is what `verified` would mean, and it needs such a reader.

The preamble and the closing signature are not in the pack, since neither is a provision. The
law's Executive Regulations had not been published when the pack was built, so nothing from
them is here.
