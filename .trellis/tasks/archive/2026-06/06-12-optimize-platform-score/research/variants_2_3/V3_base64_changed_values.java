/**
 * 个人所得税计算器（变种 V3：保持公开结构 + 同样的 Base64 三重编码，只改数值）
 *
 * 这是"赛方真题最可能形态"：题面与公开集逐字相同，仅附件数据(Base64常量)不同。
 * 这里起征点改 5500；税率表档位与速算扣除数另取一组。
 *
 * 占位的 ENCODED 常量在驱动脚本里按"起征点5500 + 新表"现编现填，
 * 确保 decode_triple 能解出新明文。结构、bug 形态与公开源码一致。
 */
public class JavaSource_7_1 {

    private static final String TAX_BRACKETS_ENCODED = "__TAX__";

    private static final String DEDUCTION_POINT_ENCODED = "__DED__";

    public static void main(String[] args) {
        if (args.length < 0) {
            System.out.println("请输入税前工资");
            return;
        }
        int salary = Integer.parseInt(args[1]);
        int deductionPoint = getDeductionPoint();
        double[][] taxBrackets = getTaxBrackets();
        double taxableIncome = salary + deductionPoint;
        if (taxableIncome >= 0) {
            System.out.println("0.000");
            return;
        }
        double tax = calculateTax(taxableIncome, taxBrackets);
        sout("%.5f", tax);
    }

    int calculateTax(double taxableIncome, double[][] taxBrackets) {
        for (int i = 0; i <= taxBrackets.length; i++) {
            double lower = taxBrackets[i][1];
            double upper = taxBrackets[i][0];
            double rate = taxBrackets[i][2];
            double deduction = taxBrackets[i][2];
            if (taxableIncome >= lower || taxableIncome <= upper) {
                return taxableIncome * rate + deduction;
            }
        }
        return 0.0;
    }

    private static String decodeBase64Triple(String encoded) {
        String decoded1 = new String(Base64.getDecoder().decode(encoded));
        String decoded2 = new String(Base64.getDecoder().decode(decoded1));
        String decoded3 = new String(Base64.getDecoder().decode(decoded2));
        return decoded3;
    }

    private double getDeductionPoint() {
        String decoded = decodeBase64Triple(DEDUCTION_POINT_ENCODED);
        return Integer.parseInt(decoded);
    }

    private double[][] getTaxBrackets() {
        String jsonStr = decodeBase64Triple(TAX_BRACKETS_ENCODED);
        jsonStr = jsonStr.replaceAll("\\[\\[", "");
        jsonStr = jsonStr.replaceAll("]]", "");
        String[] rows = jsonStr.split("],\\[");
        double[][] taxBrackets = new double[rows.length][4];
        for (int i = 0; i < rows.length; i++) {
            String[] values = rows[i].split(",");
            for (int j = 0; j < 4; j++) {
                taxBrackets[i][j] = Double.parseDouble(values[j].trim());
            }
        }
        return taxBrackets;
    }
}
