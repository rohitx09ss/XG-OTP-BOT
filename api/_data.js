const AVG = 118; // market average

// 1) Screenshot wale countries: price bilkul same
const fixed = [
  ["US", "USA", "+1", 28],
  ["US2", "USA", "+1", 320],
  ["IN", "India", "+91", 66],
  ["ID", "Indonesia", "+62", 22],
  ["PH", "Philippines", "+63", 52],
  ["VN", "Vietnam", "+84", 49],
  ["CA", "Canada", "+1", 34],
  ["UA", "Ukraine", "+380", 25],
  ["KZ", "Kazakhstan", "+7", 264],
  ["IR", "Iran", "+98", 105],
  ["BR", "Brazil", "+55", 194],
  ["AF", "Afghanistan", "+93", 66],
  ["AL", "Albania", "+355", 77],
  ["DZ", "Algeria", "+213", 92],
  ["AO", "Angola", "+244", 64],
  ["AR", "Argentina", "+54", 60],
  ["AM", "Armenia", "+374", 66],
  ["AU", "Australia", "+61", 426],
  ["AT", "Austria", "+43", 334],
  ["AZ", "Azerbaijan", "+994", 115],
  ["BS", "Bahamas", "+1242", 62],
  ["BH", "Bahrain", "+973", 115],
  ["BD", "Bangladesh", "+880", 66],
  ["BB", "Barbados", "+1246", 52],
  ["BY", "Belarus", "+375", 66],
  ["BE", "Belgium", "+32", 383],
  ["BZ", "Belize", "+501", 96],
  ["BJ", "Benin", "+229", 111],
  ["BT", "Bhutan", "+975", 62],
  ["BO", "Bolivia", "+591", 53],
];

// 2) Baaki sab countries (price niche rule se lagega)
const others = `GB|United Kingdom|44,AG|Antigua and Barbuda|1268,BA|Bosnia|387,BW|Botswana|267,BN|Brunei|673,BG|Bulgaria|359,BF|Burkina Faso|226,BI|Burundi|257,KH|Cambodia|855,CM|Cameroon|237,CV|Cape Verde|238,CF|Central African Republic|236,TD|Chad|235,CL|Chile|56,CN|China|86,CO|Colombia|57,KM|Comoros|269,CG|Congo|242,CD|DR Congo|243,CR|Costa Rica|506,HR|Croatia|385,CU|Cuba|53,CY|Cyprus|357,CZ|Czechia|420,DK|Denmark|45,DJ|Djibouti|253,DO|Dominican Republic|1809,EC|Ecuador|593,EG|Egypt|20,SV|El Salvador|503,EE|Estonia|372,ET|Ethiopia|251,FJ|Fiji|679,FI|Finland|358,FR|France|33,GA|Gabon|241,GM|Gambia|220,GE|Georgia|995,DE|Germany|49,GH|Ghana|233,GR|Greece|30,GT|Guatemala|502,GN|Guinea|224,GY|Guyana|592,HT|Haiti|509,HN|Honduras|504,HK|Hong Kong|852,HU|Hungary|36,IS|Iceland|354,IQ|Iraq|964,IE|Ireland|353,IL|Israel|972,IT|Italy|39,CI|Ivory Coast|225,JM|Jamaica|1876,JP|Japan|81,JO|Jordan|962,KE|Kenya|254,KW|Kuwait|965,KG|Kyrgyzstan|996,LA|Laos|856,LV|Latvia|371,LB|Lebanon|961,LS|Lesotho|266,LR|Liberia|231,LY|Libya|218,LT|Lithuania|370,LU|Luxembourg|352,MO|Macau|853,MG|Madagascar|261,MW|Malawi|265,MY|Malaysia|60,MV|Maldives|960,ML|Mali|223,MT|Malta|356,MR|Mauritania|222,MU|Mauritius|230,MX|Mexico|52,MD|Moldova|373,MN|Mongolia|976,ME|Montenegro|382,MA|Morocco|212,MZ|Mozambique|258,MM|Myanmar|95,NA|Namibia|264,NP|Nepal|977,NL|Netherlands|31,NZ|New Zealand|64,NI|Nicaragua|505,NE|Niger|227,NG|Nigeria|234,MK|North Macedonia|389,NO|Norway|47,OM|Oman|968,PK|Pakistan|92,PA|Panama|507,PG|Papua New Guinea|675,PY|Paraguay|595,PE|Peru|51,PL|Poland|48,PT|Portugal|351,QA|Qatar|974,RO|Romania|40,RU|Russia|7,RW|Rwanda|250,SA|Saudi Arabia|966,SN|Senegal|221,RS|Serbia|381,SL|Sierra Leone|232,SG|Singapore|65,SK|Slovakia|421,SI|Slovenia|386,SO|Somalia|252,ZA|South Africa|27,KR|South Korea|82,SS|South Sudan|211,ES|Spain|34,LK|Sri Lanka|94,SD|Sudan|249,SR|Suriname|597,SE|Sweden|46,CH|Switzerland|41,SY|Syria|963,TW|Taiwan|886,TJ|Tajikistan|992,TZ|Tanzania|255,TH|Thailand|66,TG|Togo|228,TT|Trinidad and Tobago|1868,TN|Tunisia|216,TR|Turkey|90,TM|Turkmenistan|993,UG|Uganda|256,AE|UAE|971,UY|Uruguay|598,UZ|Uzbekistan|998,VE|Venezuela|58,YE|Yemen|967,ZM|Zambia|260,ZW|Zimbabwe|263`;

// 3) Top 50 countries (list me sabse upar dikhengi)
const TOP50 = [
  "US", "IN", "GB", "ID", "PH", "VN", "CA", "UA", "KZ", "IR",
  "BR", "RU", "PK", "NG", "MX", "TH", "MY", "EG", "TR", "SA",
  "AE", "ZA", "KE", "DE", "FR", "ES", "IT", "PL", "NL", "CN",
  "JP", "KR", "CO", "CL", "PE", "VE", "LK", "NP", "MM", "KH",
  "GH", "MA", "UZ", "IL", "RO", "PT", "BD", "AU", "AR", "BY",
];

// Top50 ka price: 22 se 78 ke beech (har country ka fixed, har baar same)
function topPrice(code) {
  let h = 0;
  for (const ch of code) h = (h * 31 + ch.charCodeAt(0)) % 1000;
  return 22 + (h % 57); // 22..78
}

const list = fixed.map(([code, name, dial, price]) => ({ code, name, dial, price }));
let marketIdx = 0;
others.split(",").forEach((row) => {
  const [code, name, dial] = row.split("|");
  const price = TOP50.includes(code)
    ? topPrice(code)
    : (marketIdx++ % 2 === 0 ? AVG - 5 : AVG + 5); // 113 / 123
  list.push({ code, name, dial: "+" + dial, price });
});

// Order: pehle top50 (US ke baad US2), phir baaki A-Z
const top = [];
TOP50.forEach((c) => {
  const x = list.find((i) => i.code === c);
  if (x) top.push(x);
  if (c === "US") top.push(list.find((i) => i.code === "US2"));
});
const rest = list
  .filter((i) => !top.includes(i))
  .sort((a, b) => a.name.localeCompare(b.name));

export const countries = [...top, ...rest];
