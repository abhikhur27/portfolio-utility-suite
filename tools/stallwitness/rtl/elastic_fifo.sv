// A four-entry single-clock FIFO, with explicit mutation switches for checker evaluation.
module elastic_fifo #(parameter W=16, DEPTH=4, MUTATION=0)(
 input logic clk,rst,input logic in_valid,output logic in_ready,input logic[W-1:0] in_data,
 output logic out_valid,input logic out_ready,output logic[W-1:0] out_data);
 localparam P=$clog2(DEPTH);
 logic[W-1:0] mem[0:DEPTH-1];logic[P-1:0] wp,rp;logic[P:0] count;logic[W-1:0] tick;
 wire push=in_valid&&in_ready;
 wire pop=out_valid&&(MUTATION==2 ? 1'b1 : out_ready);
 assign in_ready=(count<DEPTH);
 assign out_valid=(count!=0);
 assign out_data=(MUTATION==1 && out_valid && !out_ready)?mem[rp]^tick:mem[rp];
 always_ff @(posedge clk) begin
  if(rst)begin wp<=0;rp<=0;count<=0;tick<=0;end
  else begin
   tick<=tick+1;
   if(push)begin mem[wp]<=in_data;wp<=wp+1'b1;end
   if(pop && MUTATION!=3)rp<=rp+1'b1;
   case({push,pop})2'b10:count<=count+1'b1;2'b01:count<=count-1'b1;default:count<=count;endcase
  end
 end
endmodule
