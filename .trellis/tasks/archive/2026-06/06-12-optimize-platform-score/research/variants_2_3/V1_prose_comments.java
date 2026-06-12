/**
 * 个人所得税计算器（变种 V1：税率表搬进散文/markdown 注释，删除 Base64 常量）
 *
 * 功能：输入税前工资（月薪），输出应缴纳个人所得税
 *
 * 【计算规则】
 * 起征点为 5000 元。应纳税所得额 = 月薪 - 起征点。
 * 应纳税额 = 应纳税所得额 × 税率 - 速算扣除数；不超过起征点时税额为 0。
 *
 * 税率表（应纳税所得额）：
 * 不超过3000元: 税率3%, 速算扣除0
 * 超过3000至12000元: 税率10%, 速算扣除410
 * 超过12000至25000元: 税率20%, 速算扣除2660
 * 超过25000至35000元: 税率25%, 速算扣除4410
 * 超过35000至55000元: 税率30%, 速算扣除7160
 * 超过55000至80000元: 税率35%, 速算扣除15160
 * 超过80000元以上: 税率45%, 速算扣除15310
 */
public class JavaSource_7_1 {
    public static void main(String[] args) {
        int salary = Integer.parseInt(args[1]);
        int deductionPoint = 5000;
        double taxableIncome = salary + deductionPoint;
        if (taxableIncome >= 0) {
            System.out.println("0.000");
            return;
        }
        // (buggy body omitted; rules are in the comments above)
    }
}
