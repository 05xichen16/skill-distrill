/**
 * 个人所得税计算器（变种 V4：二维数组字面量，税率写成百分数整数，换起征点）
 *
 * 起征点 5000（与公开相同），但税率表用 [上限, 税率%, 速算扣除] 的二维字面量，
 * 且税率用整数百分比（3 表示 3%）。档位值取一组不同于公开的值。
 */
public class JavaSource_7_1 {
    static final int DEDUCTION_POINT = 5000;
    // {上限, 税率(百分比), 速算扣除数}
    static final double[][] TAX_TABLE = {
        {4000, 4, 0},
        {15000, 12, 320},
        {30000, 22, 1820},
        {45000, 28, 3620},
        {65000, 33, 5870},
        {95000, 38, 9120},
        {999999999, 50, 20520}
    };

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
