/**
 * 个人所得税计算器（变种 V2：平行数组 + 换一组档位值 + 换起征点）
 *
 * 起征点改为 6000；税率表档位/速算扣除数全部不同于公开值。
 * 应纳税所得额 = 月薪 - 起征点；应纳税额 = 应纳税所得额 × 税率 - 速算扣除数。
 *
 * 注：这里故意用平行数组承载表，且不出现 TAX_BRACKETS_ENCODED / DEDUCTION_POINT_ENCODED。
 */
public class JavaSource_7_1 {
    static final int DEDUCTION_POINT = 6000;
    // 上限（应纳税所得额），最后一档用大数代表无穷
    static final double[] upperLimits = {2000, 8000, 20000, 40000, 70000, 110000, 999999999};
    // 税率（百分比）
    static final double[] taxRates = {2, 8, 15, 22, 28, 36, 48};
    // 速算扣除数
    static final double[] quickDeductions = {0, 120, 680, 2080, 4180, 9780, 23980};

    public static void main(String[] args) {
        int salary = Integer.parseInt(args[1]);
        double taxableIncome = salary + DEDUCTION_POINT;
        if (taxableIncome >= 0) {
            System.out.println("0.000");
            return;
        }
        // (buggy body omitted)
    }
}
