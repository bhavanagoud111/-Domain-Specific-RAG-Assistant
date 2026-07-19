# Week 6 — Phase 1b tourism mislabeling audit (all 50 countries)

Detector v2: source_url on state.gov/cdc.gov, OR >=2 case-sensitive State Dept /
CDC phrase matches in the chunk text. Run POST-fix, hence 0 mislabeled.

```
country                tourism state_dept  cdc  MISLABELED
----------------------------------------------------------
Argentina                    1          2   11           0
Australia                    4          2   10           0
Austria                      3          2    9           0
Brazil                       2          4   13           0
Cambodia                    48         20   12           0
Canada                       1         13    8           0
Chile                        3          2   10           0
China                        2         32   12           0
Colombia                     3         18   12           0
Costa Rica                   3         17   12           0
Croatia                     34         15   10           0
Czech Republic              49         16    9           0
Dominican Republic           2         14   12           0
Egypt                       50         19   11           0
France                       2         15    9           0
Germany                      7         15    9           0
Greece                      53         16    9           0
Iceland                     34         19    9           0
India                        9         25   14           0
Indonesia                   14          2   12           0
Ireland                      7         14    9           0
Israel                      66          5   10           0
Italy                       19         17    9           0
Japan                      114         15    9           0
Jordan                       2         23   10           0
Malaysia                     2         21   12           0
Mexico                      57         34   13           0
Morocco                     49          2   10           0
Nepal                        2         19   11           0
Netherlands                  2          2    9           0
New Zealand                 78         15    9           0
Norway                      10          2    9           0
Peru                        53          4   13           0
Philippines                  2          3   12           0
Poland                       5          2    9           0
Portugal                     4         15    9           0
Saudi Arabia                43         30   12           0
Singapore                   99         14   10           0
South Africa                 3         16   12           0
South Korea                 84         14   11           0
Spain                        2         14    9           0
Sri Lanka                   36         15   11           0
Sweden                      55          2    9           0
Switzerland                 12         15    9           0
Thailand                     2          3   12           0
Turkey                      11         24   10           0
United Arab Emirates         2          3   11           0
United Kingdom               7         13    9           0
United States                3          0    1           0
Vietnam                     24          2   12           0
----------------------------------------------------------
TOTAL                     1179        626  514           0

AFFECTED COUNTRIES: 0 -> []
```
